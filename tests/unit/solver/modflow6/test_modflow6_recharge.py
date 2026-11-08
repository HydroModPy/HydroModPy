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
from hydromodpy.solver.modflow6.build import _shared_recharge_dir
from hydromodpy.solver.modflow6.builders.recharge import (
    PRIVATE_TRIAL_RECHARGE_KEY,
    RECHARGE_BINARY_MIN_PERIODS,
    TRIAL_RECHARGE_DIRNAME,
    bind_recharge_from_flow,
    externalize_recharge_spd,
    recharge_to_spd,
    resolve_deferred_heterogeneous_recharge,
)
from tests._helpers.mf6_toy_models import (
    toy_model,
    two_triangle_model,
)


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


def test_modflow6_binds_recharge_from_flow_sinks_sources() -> None:
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


def test_modflow6_rejects_nonfinite_direct_recharge() -> None:
    model = toy_model()
    model.recharge = np.asarray([1.0e-8, np.nan], dtype=float)

    with pytest.raises(ValueError, match="model.recharge"):
        bind_recharge_from_flow(model)


def test_modflow6_rejects_bad_recharge_flat_shape() -> None:
    model = toy_model()
    model.recharge = np.asarray([1.0e-8, 2.0e-8, 3.0e-8], dtype=float)

    with pytest.raises(ValueError, match="sequence length"):
        recharge_to_spd(model)


def test_modflow6_single_period_recharge_sequence_uses_first_clim() -> None:
    model = toy_model()
    model.nper = 1
    model.first_clim = "mean"
    model.recharge = np.asarray([1.0e-8, 2.0e-8, 3.0e-8], dtype=float)

    spd = recharge_to_spd(model)

    assert np.allclose(spd[0], 2.0e-8)


def test_modflow6_rejects_missing_recharge_mapping_period() -> None:
    model = toy_model()
    model.recharge = {0: np.full(6, 1.0e-8, dtype=float)}

    with pytest.raises(ValueError, match=r"gives no rate for period\(s\) \[1\]"):
        recharge_to_spd(model)


def test_modflow6_resolves_point_recharge_on_unstructured_runtime_mesh() -> None:
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


def test_modflow6_defaults_to_zero_recharge_when_inactive() -> None:
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
# assumption, so its trials mark themselves with
# ``PRIVATE_TRIAL_RECHARGE_KEY`` and each gets its own ``<trial>/_recharge``
# folder instead, wherever the model that asks for it sits (leaf, nested, or the
# ``_ssic`` steady-state auxiliary model).

_SCRATCH = os.path.join(os.sep, "p", ".hmp", "scratch")


_TRIAL = os.path.join(_SCRATCH, "run_trial000016")


_OVERRIDES = {PRIVATE_TRIAL_RECHARGE_KEY: True}


def test_a_leaf_model_writes_into_its_own_trial_recharge_folder() -> None:
    model = SimpleNamespace(full_path=_TRIAL, _flow_runtime_overrides=_OVERRIDES)
    assert _shared_recharge_dir(model) == os.path.join(_TRIAL, TRIAL_RECHARGE_DIRNAME)


def test_a_nested_model_still_finds_its_trial_folder() -> None:
    nested = os.path.join(_TRIAL, "cheze_cal_377f4b")
    model = SimpleNamespace(full_path=nested, _flow_runtime_overrides=_OVERRIDES)
    assert _shared_recharge_dir(model) == os.path.join(_TRIAL, TRIAL_RECHARGE_DIRNAME)


def test_the_ssic_auxiliary_model_shares_its_parent_trials_folder() -> None:
    ssic = os.path.join(_TRIAL, "cheze_cal_377f4b", "_ssic", "ssic")
    model = SimpleNamespace(full_path=ssic, _flow_runtime_overrides=_OVERRIDES)
    assert _shared_recharge_dir(model) == os.path.join(_TRIAL, TRIAL_RECHARGE_DIRNAME)


def test_without_the_key_a_trial_keeps_using_the_shared_folder() -> None:
    model = SimpleNamespace(full_path=_TRIAL, _flow_runtime_overrides={})
    assert _shared_recharge_dir(model) == os.path.join(_SCRATCH, "_shared_recharge")


def test_a_trial_with_no_overrides_at_all_keeps_using_the_shared_folder() -> None:
    model = SimpleNamespace(full_path=_TRIAL)
    assert _shared_recharge_dir(model) == os.path.join(_SCRATCH, "_shared_recharge")


def test_outside_a_trial_there_is_no_recharge_folder_at_all() -> None:
    model = SimpleNamespace(
        full_path=os.path.join(_SCRATCH, "plain_run"), _flow_runtime_overrides=_OVERRIDES
    )
    assert _shared_recharge_dir(model) is None


# Recharge keeps its RCHA name and header when EVTA gains the same machinery.
#
# ``externalize_recharge_spd`` grew a ``package`` parameter for the soil ETP
# (EVTA); called without it (every non-soil model, and every model built before
# this change) it must still name files ``*.rcha.<k>.bin`` / ``rcha_<digest>.<k>.bin``
# and write the ``RECHARGE`` header, byte for byte.

_NCPL = 4


_NPER = RECHARGE_BINARY_MIN_PERIODS + 2


def _stack() -> dict[int, np.ndarray]:
    return {kper: np.full(_NCPL, 1.0e-8 * (kper + 1)) for kper in range(_NPER)}


def test_the_default_package_names_local_files_rcha() -> None:
    payload = externalize_recharge_spd(_stack(), basename="m")

    for kper, record in payload.items():
        assert record["filename"] == f"m.rcha.{kper}.bin"


def test_the_default_package_names_shared_files_rcha_and_writes_the_recharge_header(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "_shared_recharge"
    payload = externalize_recharge_spd(_stack(), basename="m", shared_dir=str(shared))

    for kper, record in payload.items():
        target = Path(record["filename"])
        assert target.name.startswith("rcha_")
        assert target.name.endswith(f".{kper}.bin")
        header_text = target.read_bytes()[24:40].decode("ascii")
        assert header_text.strip() == "RECHARGE"


# The recharge stack must not survive the package that consumed it.
#
# On a long chronicle the stack is the largest array a MODFLOW 6 model builds:
# measured on the Nancon at 25 m, 1826 periods x 243 552 cells x 8 bytes = 3.31 GB.
# On the shared calibration path FloPy is handed FILENAMES without the arrays, so
# anything still holding the stack holds it for the whole solve, once per
# concurrent trial. It used to be ``model.rch_spd``, an attribute nothing in the
# package ever read.

N_CELLS = 32


N_PERIODS = RECHARGE_BINARY_MIN_PERIODS + 4


def _stack_3() -> dict[int, np.ndarray]:
    return {kper: np.full(N_CELLS, 1e-8 * (kper + 1), dtype="float64") for kper in range(N_PERIODS)}


def test_the_shared_payload_hands_filenames_and_not_the_arrays(tmp_path) -> None:
    payload = externalize_recharge_spd(_stack_3(), basename="m", shared_dir=tmp_path)

    assert set(payload) == set(range(N_PERIODS))
    for record in payload.values():
        assert "filename" in record
        assert "data" not in record, "the array travels to FloPy and stays alive with it"


def test_nothing_in_the_payload_keeps_the_stack_alive(tmp_path) -> None:
    spd = _stack_3()
    watchers = {kper: weakref.ref(arr) for kper, arr in spd.items()}

    payload = externalize_recharge_spd(spd, basename="m", shared_dir=tmp_path)
    del spd
    gc.collect()

    alive = [kper for kper, ref in watchers.items() if ref() is not None]
    assert not alive, f"{len(alive)} period(s) of the stack outlived their externalisation"
    assert len(payload) == N_PERIODS


def test_a_short_chronicle_is_left_internal_and_keeps_its_arrays(tmp_path) -> None:
    # Below the threshold the arrays ARE the payload, so they must stay alive:
    # the guard above must not be read as "always drop the data".
    short = {kper: np.zeros(N_CELLS) for kper in range(RECHARGE_BINARY_MIN_PERIODS - 1)}
    payload = externalize_recharge_spd(short, basename="m", shared_dir=tmp_path)

    assert payload is short


def test_the_model_never_carries_the_stack_as_an_attribute() -> None:
    # The retention this module exists for. `rch_spd` had no reader anywhere in
    # the package, so re-introducing the attribute is the regression to catch.
    import inspect

    from hydromodpy.solver.modflow6 import build

    # Comments are stripped: the line explaining WHY the attribute is gone names
    # it, and a test that matched its own explanation would never fail.
    code = [
        line for line in inspect.getsource(build).splitlines() if not line.lstrip().startswith("#")
    ]
    offenders = [line.strip() for line in code if "model.rch_spd" in line]
    assert not offenders, (
        f"the recharge stack is back on the model ({offenders}); it holds 3.31 GB per "
        "trial on a daily five-year chronicle and nothing reads it"
    )
