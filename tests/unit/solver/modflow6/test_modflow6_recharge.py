"""Recharge (m/s per cell) bound from the flow config, and its stress-period payload.

Recharge comes as a rate per period, flat over the cells of a DISV grid. Lake cells
get none, since LAK carries rainfall and open-water evaporation itself. A long
chronicle goes to binary files named RCHA, and the stack must not stay in memory.
"""

from __future__ import annotations

import gc
import os
import weakref
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.base.plan import RunSlot
from hydromodpy.solver.modflow6.builders.recharge import (
    RECHARGE_BINARY_MIN_PERIODS,
    _shared_forcing_dir,
    as_recharge_flat,
    bind_recharge_from_flow,
    build_evt_stress_period_data,
    clip_negative_payload,
    copy_runtime_payload,
    externalize_recharge_spd,
    extract_evt_payload,
    extract_evt_payload_2d,
    mask_recharge_on_lake_cells,
    payload_has_negative_values,
    recharge_to_spd,
    resolve_deferred_heterogeneous_recharge,
    resolve_deferred_soil_etp,
)
from hydromodpy.solver.modflow6.modflow6_config import _coerce_modflow6_config
from hydromodpy.solver.modflow6.support.steady_initial_conditions import auxiliary_slot
from tests._helpers.forcing_cases import grid_source
from tests._helpers.mf6_toy_models import (
    toy_model,
    two_triangle_model,
)
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


def _make_recharge_point_record(
    *,
    station_id: str,
    x: float,
    y: float,
    january_value_mm_day: float,
    february_value_mm_day: float | None = None,
) -> PointRecord:
    dates = pd.date_range("2003-01-01", "2003-02-28", freq="D")
    values = np.full(len(dates), float(january_value_mm_day), dtype=float)
    if february_value_mm_day is not None:
        values[dates.month == 2] = float(february_value_mm_day)
    return PointRecord(
        station_id=station_id,
        variable="recharge",
        source="test",
        unit="mm/day",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": values}),
        date_start=datetime(2003, 1, 1),
        date_end=datetime(2003, 2, 28),
        location=StationLocation(id=station_id, x=x, y=y, crs="EPSG:2154"),
    )


def test_recharge_from_flow_config() -> None:
    model = toy_model()
    model.inputs = replace(
        model.inputs,
        recharge=FlowRechargeConfig(
            values=pd.Series([0.5, 0.3], dtype=float),
            first_clim="first",
            units="mm/day",
        ),
        active_sinks_sources=("recharge",),
    )

    bind_recharge_from_flow(model)
    spd = recharge_to_spd(model)

    # DISV: recharge arrays are flat (ncpl,)
    assert spd[0].shape == (6,)
    assert np.allclose(spd[0], 0.5e-3 / 86400.0)
    assert np.allclose(spd[1], 0.3e-3 / 86400.0)


REFUSALS = [
    pytest.param(
        np.asarray([1.0e-8, np.nan], dtype=float),
        bind_recharge_from_flow,
        "model.recharge",
        id="nonfinite direct recharge",
    ),
    pytest.param(
        np.asarray([1.0e-8, 2.0e-8, 3.0e-8], dtype=float),
        recharge_to_spd,
        "sequence length",
        id="sequence of the wrong length",
    ),
    pytest.param(
        {0: np.full(6, 1.0e-8, dtype=float)},
        recharge_to_spd,
        r"gives no rate for period\(s\) \[1\]",
        id="mapping without a period",
    ),
]


@pytest.mark.parametrize(("recharge", "call", "message"), REFUSALS)
def test_refusals(recharge, call, message) -> None:
    model = toy_model()
    model.recharge = recharge

    with pytest.raises(ValueError, match=message):
        call(model)


def test_single_period_sequence_uses_first_clim() -> None:
    model = toy_model()
    model.nper = 1
    model.first_clim = "mean"
    model.recharge = np.asarray([1.0e-8, 2.0e-8, 3.0e-8], dtype=float)

    spd = recharge_to_spd(model)

    assert np.allclose(spd[0], 2.0e-8)


def test_point_recharge_on_a_triangle_mesh() -> None:
    model = two_triangle_model()
    point = _make_recharge_point_record(
        station_id="R1",
        x=0.75,
        y=0.25,
        january_value_mm_day=8.0,
    )
    model.inputs = replace(
        model.inputs,
        recharge=FlowRechargeConfig(
            values=0.0,
            heterogeneous_source=LoadResult(points=[point]),
            interpolation_method="nearest",
        ),
        active_sinks_sources=("recharge",),
    )

    bind_recharge_from_flow(model)
    resolve_deferred_heterogeneous_recharge(model)

    expected = 8.0e-3 / 86400.0
    np.testing.assert_allclose(
        model.recharge[0],
        np.full(2, expected, dtype=float),
    )
    np.testing.assert_allclose(
        model.recharge[1],
        np.full(2, expected, dtype=float),
    )


def test_zero_recharge_when_inactive() -> None:
    model = toy_model()
    model.inputs = replace(model.inputs, active_sinks_sources=())

    bind_recharge_from_flow(model)
    spd = recharge_to_spd(model)

    assert spd[0].shape == (6,)
    assert np.allclose(spd[0], 0.0)
    assert np.allclose(spd[1], 0.0)


# A trial that samples the recharge writes it into its own folder, not the shared one.
#
# The calibration-wide ``_shared_recharge`` dir assumes the recharge is invariant
# across trials. A phase that samples a recharge parameter breaks that
# assumption, so the sandbox of each of its trials names a folder of its own,
# ``<trial>/_recharge``, in ``shared_forcing_dir`` of the slot. The build reads
# the folder the slot names, wherever the model sits (leaf, nested, or the
# ``_ssic`` steady-state auxiliary model, whose slot derives from its parent's),
# and never its own path.

_SCRATCH = os.path.join(os.sep, "p", ".hmp", "scratch")
_TRIAL = os.path.join(_SCRATCH, "run_trial000016")
_PRIVATE = os.path.join(_TRIAL, "_recharge")
_SHARED = os.path.join(_SCRATCH, "_shared_recharge")


def _model_in(folder: str, name: str, shared_forcing_dir: str | None) -> SimpleNamespace:
    return SimpleNamespace(slot=RunSlot(folder, name, shared_forcing_dir=shared_forcing_dir))


def _ssic_of(parent: SimpleNamespace) -> SimpleNamespace:
    folder = os.path.join(str(parent.slot.directory), "_ssic")
    return SimpleNamespace(slot=auxiliary_slot(parent, Path(folder), "ssic"))


SHARED_FORCING_CASES = (
    (
        "a leaf model writes into its own trial folder",
        _model_in(_SCRATCH, "run_trial000016", _PRIVATE),
        _PRIVATE,
    ),
    (
        "a nested model writes into the folder of its trial",
        _model_in(_TRIAL, "cheze_cal_377f4b", _PRIVATE),
        _PRIVATE,
    ),
    (
        "the ssic model shares the folder of its parent",
        _ssic_of(_model_in(_TRIAL, "cheze", _PRIVATE)),
        _PRIVATE,
    ),
    ("a trial of a session uses the shared folder", _model_in(_TRIAL, "cheze", _SHARED), _SHARED),
    (
        "the ssic model of a session trial shares it",
        _ssic_of(_model_in(_TRIAL, "cheze", _SHARED)),
        _SHARED,
    ),
    (
        "outside a trial the files stay beside the model",
        _model_in(_SCRATCH, "plain_run", None),
        None,
    ),
    ("a model built without a slot keeps them beside it too", SimpleNamespace(), None),
)


@pytest.mark.parametrize(
    ("case", "model", "expected"),
    SHARED_FORCING_CASES,
    ids=[case for case, _, _ in SHARED_FORCING_CASES],
)
def test_recharge_folder(case: str, model: SimpleNamespace, expected: str | None) -> None:
    del case
    assert _shared_forcing_dir(model) == expected


# Recharge keeps its RCHA name and header when EVTA gains the same machinery.
#
# ``externalize_recharge_spd`` grew a ``package`` parameter for the soil ETP
# (EVTA); called without it (every non-soil model, and every model built before
# this change) it must still name files ``*.rcha.<k>.bin`` / ``rcha_<digest>.<k>.bin``
# and write the ``RECHARGE`` header, byte for byte.


def recharge_stack(n_cells: int, n_periods: int) -> dict[int, np.ndarray]:
    return {kper: np.full(n_cells, 1.0e-8 * (kper + 1)) for kper in range(n_periods)}


def test_default_package_names_files_rcha() -> None:
    payload = externalize_recharge_spd(
        recharge_stack(4, RECHARGE_BINARY_MIN_PERIODS + 2), basename="m"
    )

    for kper, record in payload.items():
        assert record["filename"] == f"m.rcha.{kper}.bin"


# The recharge stack must not survive the package that consumed it.
#
# On a long chronicle the stack is the largest array a MODFLOW 6 model builds:
# measured on the Nancon at 25 m, 1826 periods x 243 552 cells x 8 bytes = 3.31 GB.
# On the shared calibration path FloPy is handed FILENAMES without the arrays, so
# anything still holding the stack holds it for the whole solve, once per
# concurrent trial. It used to be ``model.rch_spd``, an attribute nothing in the
# package ever read.

N_PERIODS = RECHARGE_BINARY_MIN_PERIODS + 4


def test_shared_payload_holds_filenames_only(tmp_path) -> None:
    payload = externalize_recharge_spd(
        recharge_stack(32, N_PERIODS), basename="m", shared_dir=tmp_path
    )

    assert set(payload) == set(range(N_PERIODS))
    for record in payload.values():
        assert "filename" in record
        assert "data" not in record, "the array travels to FloPy and stays alive with it"


def test_payload_does_not_keep_the_stack_alive(tmp_path) -> None:
    spd = recharge_stack(32, N_PERIODS)
    watchers = {kper: weakref.ref(arr) for kper, arr in spd.items()}

    payload = externalize_recharge_spd(spd, basename="m", shared_dir=tmp_path)
    del spd
    gc.collect()

    alive = [kper for kper, ref in watchers.items() if ref() is not None]
    assert not alive, f"{len(alive)} period(s) of the stack outlived their externalisation"
    assert len(payload) == N_PERIODS


def test_model_does_not_carry_the_stack() -> None:
    # The retention this module exists for. `rch_spd` had no reader anywhere in
    # the package, so re-introducing the attribute is the regression to catch.
    import inspect

    from hydromodpy.solver.modflow6 import build
    from hydromodpy.solver.modflow6.builders import recharge

    # Comments are stripped: the line explaining WHY the attribute is gone names
    # it, and a test that matched its own explanation would never fail.
    code = [
        line
        for module in (build, recharge)
        for line in inspect.getsource(module).splitlines()
        if not line.lstrip().startswith("#")
    ]
    offenders = [line.strip() for line in code if "model.rch_spd" in line]
    assert not offenders, (
        f"the recharge stack is back on the model ({offenders}); it holds 3.31 GB per "
        "trial on a daily five-year chronicle and nothing reads it"
    )


def test_recharge_is_zeroed_on_lake_cells_only() -> None:
    spd = {0: np.full(6, 1.0e-8), 1: np.full(6, 2.0e-8)}

    masked = mask_recharge_on_lake_cells(spd, lake_cell_ids=[1, 4])

    for kper, rate in ((0, 1.0e-8), (1, 2.0e-8)):
        np.testing.assert_array_equal(masked[kper], [rate, 0.0, rate, rate, 0.0, rate])


def test_no_lake_leaves_the_recharge_unchanged() -> None:
    masked = mask_recharge_on_lake_cells({0: np.full(4, 3.0e-8)}, lake_cell_ids=[])

    assert np.all(masked[0] == 3.0e-8)


EVT_CASES = [
    pytest.param([2, 4], {0, 1, 3, 5}, id="lake cells carry no EVT"),
    pytest.param(None, set(range(6)), id="every cell without lake cells"),
]


@pytest.mark.parametrize(("lake_cell_ids", "cells_with_evt"), EVT_CASES)
def test_evt_records_skip_lake_cells(lake_cell_ids, cells_with_evt) -> None:
    mesh = solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=3,
        top=np.full((2, 3), 10.0),
        botm=np.stack([np.full((2, 3), 5.0), np.full((2, 3), 0.0)]),
    )
    model = SimpleNamespace(
        ncpl=6,
        nper=1,
        modflow_config=_coerce_modflow6_config(None),
        _evt_rate_payload={0: 1.0e-8},  # uniform routed deficit, m/s
    )
    no_cells = np.zeros(mesh.n_cells, dtype=bool)
    # lake_cell_ids is passed explicitly so the masking does not depend on build order.
    extra = {} if lake_cell_ids is None else {"lake_cell_ids": lake_cell_ids}

    evt_spd = build_evt_stress_period_data(
        model, mesh, ocean_support_mask=no_cells, stream_support_mask=no_cells, **extra
    )

    assert {int(entry[1]) for entry in evt_spd[0]} == cells_with_evt


NEGATIVE_PAYLOADS = [
    pytest.param(-1.0e-9, True, id="negative scalar"),
    pytest.param(0.0, False, id="zero scalar"),
    pytest.param(
        {0: np.full(3, 1.0e-8), 1: np.asarray([1.0e-8, -1.0e-8, 0.0])}, True, id="mapping"
    ),
    pytest.param({0: 1.0e-8, 1: np.full(3, 2.0e-8)}, False, id="mapping of rates"),
    pytest.param([1.0e-8, -2.0e-8], True, id="list"),
]


@pytest.mark.parametrize(("payload", "expected"), NEGATIVE_PAYLOADS)
def test_payload_has_negative_values(payload, expected) -> None:
    assert payload_has_negative_values(payload) is expected


CLIPPED_PAYLOADS = [
    pytest.param(-2.0e-8, 0.0, id="negative scalar"),
    pytest.param(3.0e-8, 3.0e-8, id="positive scalar"),
    pytest.param(np.asarray(-1.0e-8), 0.0, id="zero-dimension array"),
    pytest.param(np.asarray([1.0e-8, -2.0e-8]), [1.0e-8, 0.0], id="array"),
    pytest.param([1.0e-8, -2.0e-8], [1.0e-8, 0.0], id="list"),
    pytest.param(pd.Series([-1.0e-8, 4.0e-8]), [0.0, 4.0e-8], id="series"),
    pytest.param(
        {0: -1.0e-8, 1: np.asarray([2.0e-8, -3.0e-8])}, {0: 0.0, 1: [2.0e-8, 0.0]}, id="mapping"
    ),
]


@pytest.mark.parametrize(("payload", "expected"), CLIPPED_PAYLOADS)
def test_clip_negative_payload(payload, expected) -> None:
    clipped = clip_negative_payload(payload)

    if isinstance(expected, dict):
        assert set(clipped) == set(expected)
        for key, value in expected.items():
            np.testing.assert_allclose(clipped[key], value)
    else:
        np.testing.assert_allclose(np.asarray(clipped, dtype=float), expected)


class UncopyableRate:
    def copy(self):
        raise RuntimeError("no copy")


def test_runtime_payload_copy_is_detached() -> None:
    rates = np.asarray([1.0e-8, 2.0e-8])
    stuck = UncopyableRate()
    payload = {"a": rates, "b": {"c": stuck}, "d": 5}

    copied = copy_runtime_payload(payload)
    rates[0] = 9.0

    np.testing.assert_allclose(copied["a"], [1.0e-8, 2.0e-8])
    assert copied["b"]["c"] is stuck  # a payload that cannot copy itself is kept as it is
    assert copied["d"] == 5


def test_negative_recharge_without_deficit_stays_whole() -> None:
    rch = {0: np.full(2, 1.0e-8), 1: np.full(2, 2.0e-8)}

    kept, deficit = extract_evt_payload_2d(
        rch, True, steady=[False, False], first_clim="mean", durations=[86400.0, 86400.0]
    )

    assert deficit is None
    np.testing.assert_allclose(kept[1], 2.0e-8)


def evt_model() -> SimpleNamespace:
    return SimpleNamespace(
        first_clim="mean", steady=[False, False], perlen=[86400.0, 86400.0], nper=2
    )


def test_negative_recharge_goes_to_evt() -> None:
    # Transient periods keep their own deficit, the clipped rate stays in RCH.
    payload = {0: np.asarray([-2.0e-8, 1.0e-8]), 1: np.asarray([1.0e-8, 1.0e-8])}

    rch, evt = extract_evt_payload(evt_model(), payload, True)

    np.testing.assert_allclose(rch[0], [0.0, 1.0e-8])
    np.testing.assert_allclose(evt[0], [2.0e-8, 0.0])
    np.testing.assert_allclose(evt[1], [0.0, 0.0])


def test_positive_recharge_has_no_evt() -> None:
    payload = np.asarray([1.0e-8, 2.0e-8])

    rch, evt = extract_evt_payload(evt_model(), payload, True)

    assert rch is payload
    assert evt is None


FLAT_RECHARGE = [
    pytest.param(np.asarray(2.0e-8), None, np.full(4, 2.0e-8), id="zero-dimension array"),
    pytest.param(np.arange(4.0), None, np.arange(4.0), id="one value per cell"),
    pytest.param(np.arange(4.0).reshape(2, 2), None, np.arange(4.0), id="grid array"),
    pytest.param(
        np.arange(12.0).reshape(3, 2, 2), 1, [4.0, 5.0, 6.0, 7.0], id="entry of the period"
    ),
]


@pytest.mark.parametrize(("value", "kper", "expected"), FLAT_RECHARGE)
def test_flat_recharge(value, kper, expected) -> None:
    np.testing.assert_allclose(
        as_recharge_flat(SimpleNamespace(ncpl=4), value, kper=kper), expected
    )


FLAT_REFUSALS = [
    pytest.param(
        np.ones(3), None, r"must be scalar or length ncpl \(4\); got 3", id="short vector"
    ),
    pytest.param(np.ones((1, 3)), None, r"must flatten to ncpl \(4\); got 3", id="small grid"),
    pytest.param(np.ones((2, 2, 2)), None, "one leading entry per stress period", id="no period"),
    pytest.param(
        np.ones((2, 2, 2)), 2, "one leading entry per stress period", id="period past end"
    ),
    pytest.param(
        np.ones((2, 1, 3)), 0, r"must flatten to ncpl \(4\); got 3", id="small grid of a period"
    ),
]


@pytest.mark.parametrize(("value", "kper", "message"), FLAT_REFUSALS)
def test_flat_recharge_refusals(value, kper, message) -> None:
    with pytest.raises(ValueError, match=message):
        as_recharge_flat(SimpleNamespace(ncpl=4), value, kper=kper)


PERIOD_RATES = [
    pytest.param(np.asarray(1.0e-8), [np.full(6, 1.0e-8)] * 2, id="zero-dimension array"),
    pytest.param(np.asarray([2.0e-8]), [np.full(6, 2.0e-8)] * 2, id="one value"),
    pytest.param(np.arange(6.0).reshape(2, 3) * 1e-9, [np.arange(6.0) * 1e-9] * 2, id="grid array"),
    pytest.param(
        np.stack([np.full(6, 1.0e-8), np.full(6, 3.0e-8)]),
        [np.full(6, 1.0e-8), np.full(6, 3.0e-8)],
        id="one row per period",
    ),
]


@pytest.mark.parametrize(("recharge", "expected"), PERIOD_RATES)
def test_rates_of_each_period(recharge, expected) -> None:
    model = toy_model()
    model.recharge = recharge

    spd = recharge_to_spd(model)

    for kper, rate in enumerate(expected):
        np.testing.assert_allclose(spd[kper], rate)


def test_recharge_array_of_no_known_shape_is_refused() -> None:
    model = toy_model()
    model.recharge = np.ones((3, 4))

    with pytest.raises(ValueError, match="one leading entry per stress period"):
        recharge_to_spd(model)


def test_negative_recharge_stays_when_not_routed() -> None:
    payload = {0: np.asarray([-1.0e-8, 2.0e-8])}

    rch, evt = extract_evt_payload_2d(
        payload, False, steady=[False], first_clim="mean", durations=[86400.0]
    )
    kept, none = extract_evt_payload(evt_model(), payload, False)

    assert evt is None
    np.testing.assert_allclose(rch[0], [-1.0e-8, 2.0e-8])
    assert kept is payload
    assert none is None


def test_direct_recharge_is_copied_and_gets_a_first_clim() -> None:
    model = toy_model()
    rates = np.asarray([1.0e-8, 2.0e-8])
    model.recharge = rates

    bind_recharge_from_flow(model)
    rates[0] = 5.0

    np.testing.assert_allclose(model.recharge, [1.0e-8, 2.0e-8])
    assert model.first_clim == "mean"


def test_active_recharge_without_a_table_is_zero() -> None:
    model = toy_model()
    model.inputs = replace(model.inputs, recharge=None, active_sinks_sources=("recharge",))

    bind_recharge_from_flow(model)

    assert model.recharge == 0.0
    assert model.first_clim == "mean"


def test_dated_recharge_on_the_period_starts() -> None:
    model = toy_model()
    dates = pd.DatetimeIndex(["2003-01-01", "2003-02-01"])
    model.inputs = replace(
        model.inputs,
        recharge=FlowRechargeConfig(values=pd.Series([0.5, 0.3], index=dates), units="mm/day"),
        active_sinks_sources=("recharge",),
    )

    bind_recharge_from_flow(model)
    spd = recharge_to_spd(model)

    np.testing.assert_allclose(spd[0], 0.5e-3 / 86400.0)  # 0.5 mm/day in m/s
    np.testing.assert_allclose(spd[1], 0.3e-3 / 86400.0)


def a_static_field_of_6_mm_per_day() -> LoadResult:
    # Two 0.5 m pixels either way over the unit square of the two triangles.
    return grid_source(np.full((2, 2), 6.0), np.asarray([0.25, 0.75]), np.asarray([0.75, 0.25]))


def test_field_recharge_on_a_triangle_mesh() -> None:
    model = two_triangle_model()
    model._heterogeneous_recharge_source = a_static_field_of_6_mm_per_day()
    model.first_clim = "mean"

    resolve_deferred_heterogeneous_recharge(model)

    for kper in (0, 1):
        np.testing.assert_allclose(model.recharge[kper], np.full(2, 6.0e-3 / 86400.0))
    assert model._heterogeneous_recharge_source is None


def test_source_without_data_is_dropped() -> None:
    model = toy_model()
    model._heterogeneous_recharge_source = LoadResult()

    resolve_deferred_heterogeneous_recharge(model)

    assert model._heterogeneous_recharge_source is None
    assert model.recharge is None


def test_soil_etp_source_on_a_triangle_mesh() -> None:
    model = two_triangle_model()
    model._soil_etp_source = a_static_field_of_6_mm_per_day()

    resolve_deferred_soil_etp(model)

    np.testing.assert_allclose(model._soil_etp_rate[1], np.full(2, 6.0e-3 / 86400.0))


def test_second_shared_write_keeps_the_files(tmp_path) -> None:
    stack = recharge_stack(5, N_PERIODS)
    first = externalize_recharge_spd(stack, basename="m", shared_dir=tmp_path)
    files = sorted(tmp_path.iterdir())
    stamps = [f.stat().st_mtime_ns for f in files]

    second = externalize_recharge_spd(stack, basename="m", shared_dir=tmp_path)

    assert second == first
    assert sorted(tmp_path.iterdir()) == files
    assert [f.stat().st_mtime_ns for f in files] == stamps
    assert files[0].stat().st_size == 52 + 8 * 5  # header plus 5 doubles


def test_one_rate_per_cell_for_every_period() -> None:
    model = toy_model()
    model.recharge = np.arange(6.0) * 1.0e-9

    spd = recharge_to_spd(model)

    np.testing.assert_allclose(spd[1], np.arange(6.0) * 1.0e-9)


DIRECT_RECHARGE = [
    pytest.param(1.0e-8, 1.0e-8, id="one rate"),
    pytest.param({0: 1.0e-8, 1: 2.0e-8}, {0: 1.0e-8, 1: 2.0e-8}, id="rate per period"),
]


@pytest.mark.parametrize(("recharge", "expected"), DIRECT_RECHARGE)
def test_direct_recharge_forms(recharge, expected) -> None:
    model = toy_model()
    model.recharge = recharge

    bind_recharge_from_flow(model)

    assert model.recharge == expected
