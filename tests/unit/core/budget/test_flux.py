"""Per-cell budget fluxes (m3/s): outflow, drains with mover, release and seepage.

Every solver gives a per-cell flux in the MODFLOW sign, negative where water leaves
the aquifer. An outflow is never negative and a stack of periods is the sum of its periods.
A Boussinesq store without budget/surface_excess falls back to water table >= surface,
which over-reports seepage, so that fallback warns.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import hydromodpy.core.budget.flux as budget_flux
from hydromodpy.core.budget.flux import (
    _NO_FLUX_BELOW,
    RELEASE_BUDGET_KEYS,
    SURFACE_EXCESS_STATE_GROUP,
    _outflow_from_signed,
    budget_outflow,
    budget_outflow_stack,
    drain_band_depth,
    drain_stack_with_mover,
    find_drain_budget_key,
    first_finite_layer,
    inflow_outflow,
    networks_route_drainage,
    release_flux_stack,
    seepage_mask,
    select_budget_zone,
    warn_on_geometric_seepage_fallback,
)
from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.scope import CATCHMENT, DOMAIN
from hydromodpy.solver.boussinesq.extractors.flow import BoussinesqOutputAdapter
from hydromodpy.solver.modflow6.extractors import lake as mf6_lake
from hydromodpy.solver.modflow6.extractors.budget import _period_mean_record
from hydromodpy.solver.modflow6.extractors.lake import AppliedExchange, LakeObsSpec
from hydromodpy.solver.modflow6.extractors.sfr import SfrObsSpec, build_sfr_columns
from hydromodpy.solver.modflow_common.calibration_extractors import (
    _drain_outflow_on_mask,
    _positive_release_by_cell,
)
from hydromodpy.solver.modflow_nwt.extractors.flow import ModflowNwtOutputAdapter


def _zones(*zones: str) -> pd.DataFrame:
    return pd.DataFrame({"zone_id": list(zones), "value": range(len(zones))})


@pytest.mark.parametrize(
    ("frame", "rows", "label"),
    [
        (_zones(DOMAIN, CATCHMENT), [1], "the delineated catchment"),
        (_zones(DOMAIN, DOMAIN), [0, 1], "the model domain"),
        (_zones("other"), [0], "the model domain"),
        (pd.DataFrame({"value": [1, 2]}), [0, 1], "the model domain"),
    ],
    ids=["catchment-wins", "domain-only", "unknown-zone", "no-zone-column"],
)
def test_catchment_rows_win_over_domain(frame, rows, label):
    chosen, said = select_budget_zone(frame)
    assert chosen["value"].tolist() == [frame["value"].tolist()[i] for i in rows]
    assert said == label


def _model(active, networks):
    """A model double read by its ``boundaries`` and ``sfr`` members."""
    return SimpleNamespace(
        boundaries=SimpleNamespace(active_ids=tuple(active or ())),
        sfr=(networks or {}).get("sfr"),
    )


@pytest.mark.parametrize(
    ("model", "routes"),
    [
        (_model(["sfr"], {"sfr": {"a": {}}}), True),
        (_model(["SFR"], {"sfr": {"a": {"route_drainage": True}}}), True),
        (_model(["sfr"], {"sfr": {"a": {"route_drainage": False}}}), False),
        (_model(["sfr"], {"sfr": {"a": SimpleNamespace(route_drainage=False), "b": {}}}), False),
        (_model(["sfr"], {"sfr": {"a": SimpleNamespace(route_drainage=True)}}), True),
        (_model(["lak"], {"sfr": {"a": {}}}), False),
        (_model(["sfr"], {"sfr": {}}), False),
        (_model(["sfr"], None), False),
        (_model(None, None), False),
        (SimpleNamespace(), False),
    ],
    ids=[
        "default-on",
        "upper-case",
        "kept-out",
        "one-network-keeps-out",
        "attr-on",
        "lake-only",
        "no-reach",
        "no-sinks",
        "no-active",
        "bare",
    ],
)
def test_sfr_network_takes_drainage(model, routes):
    assert networks_route_drainage(model) is routes


def test_drain_budget_key():
    assert find_drain_budget_key({"drain": 1}) == "drain"
    assert find_drain_budget_key({"stream": 1}) is None
    assert find_drain_budget_key(5) is None


@pytest.mark.parametrize(
    ("signed", "n_cells", "expected"),
    [
        ([-1.0, 2.0, 0.0], 3, [1.0, 0.0, 0.0]),
        ([[-1.0, -2.0], [-3.0, 4.0]], 2, [4.0, 2.0]),  # two layers summed per cell
        ([-1.0, -2.0, -3.0, -4.0], 2, [4.0, 6.0]),  # flat field reshaped on n_cells
        ([[-1.0, -2.0], [-3.0, 4.0]], None, [4.0, 2.0]),
        ([-1.0, 2.0], None, [1.0, 0.0]),
        ([np.nan, -9999.0, 1.0, -5.0], 4, [0.0, 0.0, 0.0, 5.0]),
        (-2.5, None, [2.5]),  # a scalar is one cell
    ],
    ids=[
        "one-layer",
        "two-layers",
        "flat",
        "no-n_cells-2d",
        "no-n_cells-1d",
        "missing-values",
        "scalar",
    ],
)
def test_outflow_of_a_step(signed, n_cells, expected):
    assert budget_outflow(np.array(signed), n_cells=n_cells).tolist() == expected


def test_outflow_of_a_3d_step():
    field = -np.ones((2, 3, 4))
    out = budget_outflow(field)
    assert out.shape == (12,)
    assert out.sum() == pytest.approx(24.0)


@pytest.mark.parametrize("seed", range(5))
def test_outflow_is_never_negative(seed):
    rng = np.random.default_rng(seed)
    signed = rng.normal(size=(4, 3, 7))
    out = budget_outflow_stack(signed, n_cells=7)
    assert out.shape == (4, 7)
    assert (out >= 0).all()
    assert out.sum() == pytest.approx(-signed[signed < 0].sum())


def test_stack_is_per_period_outflow():
    rng = np.random.default_rng(0)
    signed = rng.normal(size=(5, 2, 6))
    stack = budget_outflow_stack(signed, n_cells=6)
    for t in range(5):
        np.testing.assert_allclose(stack[t], budget_outflow(signed[t], n_cells=6))


def test_empty_stack_and_wrong_rank():
    assert budget_outflow_stack(np.empty((3, 0, 0)), n_cells=4).tolist() == [[0.0] * 4] * 3
    with pytest.raises(ValueError, match="Expected a"):
        budget_outflow_stack(np.zeros(5), n_cells=5)


@pytest.mark.parametrize(
    ("budget", "key", "expected"),
    [
        ({"drain": np.array([[-1.0]])}, "drain", [[-1.0]]),
        ({"drain_to_mover": np.array([[-2.0]])}, None, [[-2.0]]),
        (
            {"drain": np.array([[-1.0]]), "drain_to_mover": np.array([[-1.0, -1.0]])},
            "drain",
            [[-1.0]],
        ),
        ({"stream": np.array([[-1.0]])}, None, None),
    ],
    ids=["drain-only", "mover-only", "shape-mismatch-keeps-drain", "neither"],
)
def test_drain_stack_from_store(budget, key, expected):
    got = drain_stack_with_mover(budget, key, 0, 1)
    assert (got is None) if expected is None else got.tolist() == expected


def test_release_keys():
    assert {"drain", "drain_to_mover", "stream", "lake", "surface_excess"} <= set(
        RELEASE_BUDGET_KEYS
    )
    assert "constant_head" not in RELEASE_BUDGET_KEYS  # an ocean is not a release to the surface


def test_release_sums_paths_out():
    budget = {
        "drain": np.array([[-1.0, 0.0, 0.0]]),
        "drain_to_mover": np.array([[-0.5, 0.0, 0.0]]),
        "stream": np.array([[0.0, -2.0, 0.0]]),
        "lake": np.array([[0.0, 0.0, -3.0]]),
        "surface_excess": np.array([[0.0, -0.25, 0.0]]),
        "recharge": np.array([[10.0, 10.0, 10.0]]),  # not a path out
        "constant_head": np.array([[-99.0, -99.0, -99.0]]),  # no role: not counted
    }
    got = release_flux_stack(budget, n_cells=3, start=0, stop=1)
    np.testing.assert_allclose(got, [[1.5, 2.25, 3.0]])


def test_release_slice():
    rng = np.random.default_rng(1)
    budget = {"drain": rng.normal(size=(6, 1, 4)), "stream": rng.normal(size=(6, 1, 4))}
    whole = release_flux_stack(budget, n_cells=4, start=0, stop=6)
    part = release_flux_stack(budget, n_cells=4, start=2, stop=5)
    np.testing.assert_allclose(part, whole[2:5])
    assert (whole >= 0).all()
    assert np.isfinite(whole).all()


def test_release_empty_slice_and_no_path():
    budget = {"drain": np.zeros((3, 1, 2))}
    assert release_flux_stack(budget, n_cells=2, start=2, stop=2).shape == (0, 2)
    with pytest.raises(KeyError, match="No release budget field"):
        release_flux_stack({"recharge": np.zeros((1, 2))}, n_cells=2, start=0, stop=1)


def test_seepage_mask_refusals():
    for kwargs in ({}, {"watertable": np.zeros(2)}, {"topography": np.zeros(2)}):
        with pytest.raises(ValueError, match="needs either surface_excess"):
            seepage_mask(**kwargs)


class _Root:
    def __init__(self, attrs):
        self.attrs = attrs


@pytest.mark.parametrize(
    ("root", "depth"),
    [
        (_Root({"drain_band_depth_m": 2.5}), 2.5),
        (_Root({}), 0.0),
        (_Root({"drain_band_depth_m": -1.0}), 0.0),
        (_Root({"drain_band_depth_m": float("nan")}), 0.0),
        (_Root({"drain_band_depth_m": float("inf")}), 0.0),
        (object(), 0.0),
        (SimpleNamespace(attrs=None), 0.0),
    ],
    ids=["band", "absent", "negative", "nan", "inf", "no-attrs", "attrs-none"],
)
def test_drain_band_depth_of_store(root, depth):
    assert drain_band_depth(root) == depth


def test_first_finite_layer() -> None:
    # A dry cell of the top layer reads the first finite layer below it.
    head = np.array(
        [
            [
                [np.nan, 5.0, np.nan],  # layer 0: the first column dry, 5.0, the last dry
                [1.5, 6.0, np.nan],  # layer 1: 1.5, dry already answered, and dry again
                [9.0, 7.0, np.nan],  # layer 2: never read, a finite layer is above
            ]
        ]
    )

    np.testing.assert_allclose(first_finite_layer(head), [[1.5, 5.0, np.nan]])


# inflow_outflow splits each (layer, cell) element: positive enters, negative leaves.
_T, _F = True, False


@pytest.mark.parametrize(
    ("stack", "support", "inflow", "outflow"),
    [
        pytest.param([[-3.0, 4.0]], None, [4.0], [3.0], id="sign"),
        pytest.param([[5.0, 100.0, 7.0, 200.0]], [_T, _F, _T, _F], [12.0], [0.0], id="mask_in"),
        pytest.param([[-3.0, -1000.0, 4.0, 9999.0]], [_T, _F, _T, _F], [4.0], [3.0], id="mask_out"),
        pytest.param([[10.0, -9999.0, 30.0]], None, [40.0], [0.0], id="sentinel_whole"),
        pytest.param([[10.0, -9999.0, 30.0]], [_T, _T, _T], [40.0], [0.0], id="sentinel_mask"),
        pytest.param([[1.0, np.nan, -2.0]], None, [1.0], [2.0], id="nan_skipped"),
        pytest.param([[-9999.0, np.nan]], None, [np.nan], [np.nan], id="no_flux_is_nan"),
        pytest.param([[np.nan, 1.0]], [_T, _F], [np.nan], [np.nan], id="none_on_support"),
        pytest.param([[[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]]], None, [66.0], [0.0], id="two_layers"),
        pytest.param([[[1.0], [-0.4]]], None, [1.0], [0.4], id="mixed_layers_split"),
        pytest.param([[[1.0], [-0.4]]], [0.5], [0.5], [0.2], id="mixed_layers_weighted"),
        pytest.param([[1.0, -2.0, 4.0, np.nan]], [1.0, 0.5, 0.25, 1.0], [2.0], [1.0], id="weights"),
        pytest.param([[np.nan, 4.0]], [1.0, 0.0], [np.nan], [np.nan], id="weight_none_counted"),
        pytest.param([[-1.0, -2.0], [3.0, -9999.0]], None, [0.0, 3.0], [3.0, 0.0], id="steps"),
    ],
)
def test_inflow_outflow_split(stack, support, inflow, outflow) -> None:
    support = None if support is None else np.asarray(support)
    got_in, got_out = inflow_outflow(np.asarray(stack, dtype=float), support)

    np.testing.assert_allclose(got_in, inflow)
    np.testing.assert_allclose(got_out, outflow)


@pytest.mark.parametrize(
    ("stack", "support", "match"),
    [
        (np.zeros(3), None, "budget stack"),
        (np.zeros((1, 1, 1, 3)), None, "budget stack"),
        (np.zeros((1, 3)), np.ones(2, dtype=bool), "support holds 2 cells"),
    ],
    ids=["one_dim", "four_dim", "support_size"],
)
def test_inflow_outflow_refusals(stack, support, match) -> None:
    with pytest.raises(ValueError, match=match):
        inflow_outflow(stack, support)


def test_net_kept_when_layers_split() -> None:
    stack = np.array([[[1.0, -3.0], [-0.4, 2.0]]])

    inflow, outflow = inflow_outflow(stack)

    assert inflow[0] - outflow[0] == pytest.approx(stack.sum())
    assert (inflow[0], outflow[0]) == pytest.approx((3.0, 3.4))


# One row per value of a budget element: whether it holds a flux. An element at or below the
# sentinel -9000 is no-data, never a flux, and so are NaN and the infinities.
_FLUX_ELEMENTS = [
    pytest.param(-2.0, True, id="a_loss"),
    pytest.param(3.0, True, id="a_gain"),
    pytest.param(0.0, True, id="zero_is_a_flux"),
    pytest.param(-8999.999, True, id="just_above_the_sentinel"),
    pytest.param(-9000.0, False, id="at_the_sentinel"),
    pytest.param(-9999.0, False, id="the_raster_nodata"),
    pytest.param(-1.0e30, False, id="a_modflow_sentinel"),
    pytest.param(np.nan, False, id="nan"),
    pytest.param(np.inf, False, id="infinite"),
]


@pytest.mark.parametrize(("value", "holds_flux"), _FLUX_ELEMENTS)
def test_sentinel_is_no_flux(value, holds_flux) -> None:
    stack = np.array([[[value]]])

    inflow, outflow = inflow_outflow(stack)

    assert _NO_FLUX_BELOW == -9000.0
    assert bool(np.isfinite(inflow[0])) is holds_flux
    assert bool(np.isfinite(outflow[0])) is holds_flux
    expected = max(-value, 0.0) if holds_flux else 0.0
    assert _outflow_from_signed(stack)[0, 0] == expected


# The signed values of the agreement table, in the sign of the aquifer: negative leaves it. The
# water that leaves is the magnitude of the negative part, and a signed zero leaves nothing.
_SIGNED = [-2.0, -0.0, 0.0, 3.0, -1.0e-12]
_OUTFLOW = [2.0, 0.0, 0.0, 0.0, 1.0e-12]


def _from_flux_module(signed, **_):
    return float(_outflow_from_signed(np.array([[[signed]]]))[0, 0])


def _from_mf6_budget(signed, **_):
    class _Cbb:
        def read_record(self, _index):
            return np.array([[[signed]]], dtype=float)

    record = _period_mean_record(
        _Cbb(),
        [(0, 1.0)],
        component="drain",
        t=0,
        nlay=1,
        n_cells=1,
        seconds_per_time_unit=1.0,
        catchment_cells=None,
    )
    return abs(record.flux_out)


def _from_sfr(signed, *, tmp_path, **_):
    # MODFLOW 6 writes the exchange positive when the stream loses water, that is when the aquifer
    # gains it, so the value is already in the sign of the aquifer. The aquifer loses what the reach gains.
    spec = SfrObsSpec.from_mapping(
        {
            "obs_csv": "s.csv",
            "network_id": "n",
            "reach_count": 1,
            "entries": [
                {"obsname": "r0_gw", "network_id": "n", "reach": 0, "quantity": "gw_exchange"}
            ],
        }
    )
    obs = tmp_path / "s.csv"
    obs.write_text(f"time,R0_GW\n1.0,{signed}\n", encoding="utf-8")
    _, budgets = build_sfr_columns(spec, obs, times=[1.0], seconds_per_time_unit=1.0)
    return budgets[0]["flux_in"]


def _from_lake(signed, *, tmp_path, monkeypatch, **_):
    # The lake exchange is positive when the lake gains water, which the aquifer loses.
    spec = LakeObsSpec.from_mapping(
        {
            "obs_csv": "l.csv",
            "entries": [{"obsname": "l_stage", "lake_id": "l", "quantity": "stage"}],
        }
    )
    obs = tmp_path / "l.csv"
    obs.write_text("TIME,L_STAGE\n1.0,90.0\n", encoding="utf-8")
    applied = {"l": AppliedExchange(total=[-signed], under_dam=None)}
    monkeypatch.setattr(mf6_lake, "read_applied_exchange", lambda *_a, **_k: applied)
    _, budgets = mf6_lake.build_lake_records(spec, obs, times=[1.0], seconds_per_time_unit=1.0)
    return budgets[0]["flux_in"]


def _from_nwt(signed, *, tmp_path, monkeypatch, **_):
    class _File:
        def __init__(self, _path, precision="double"):
            self.recordarray = np.array(
                [(1, 1, b"          DRAINS", 1, 1.0, 1.0)],
                dtype=[
                    ("kstp", "<i4"),
                    ("kper", "<i4"),
                    ("text", "S16"),
                    ("imeth", "<i4"),
                    ("delt", "<f4"),
                    ("totim", "<f4"),
                ],
            )

        def get_unique_record_names(self):
            return [b"DRAINS"]

        def get_record(self, _idx, full3D=False):
            return np.array([signed], dtype=float).reshape(1, 1, 1)

        def close(self):
            return None

    class _Store:
        budgets: list = []

        def write_budgets(self, _sim, records):
            self.budgets = records

        def write_field_stack(self, *_a, **_k):
            return None

        def open_zarr(self, _sim):
            return self

        def write_budget_policy(self, *_a):
            return None

        def close(self):
            return None

    monkeypatch.setattr("flopy.utils.binaryfile.CellBudgetFile", _File)
    store = _Store()
    ModflowNwtOutputAdapter()._extract_budget(
        "sim",
        store,
        tmp_path / "r.cbc",
        [1.0],
        [(0, 0)],
        1,
        1,
        1,
        budget_terms=BudgetKeep.everything(),
        flux_scale_to_m3_s=1.0,
    )
    return next(row for row in store.budgets if row["zone_id"] != CATCHMENT)["flux_out"]


def _from_boussinesq(signed, **_):
    # The solver counts a drain flux positive when water leaves, so the aquifer sign is turned once.
    payload = {"drainage_flux_history_m3_s": np.array([[-signed]])}
    components = BoussinesqOutputAdapter._budget_components(
        payload, n_timesteps=1, n_cells=1, cell_area_m2=None
    )
    rows: list[dict] = []

    class _Store:
        def write_budgets(self, _sim, records):
            rows.extend(records)

    BoussinesqOutputAdapter._write_budget_table("sim", _Store(), components, n_timesteps=1)
    return rows[0]["flux_out"]


def _from_calibration_drain(signed, **_):
    return _drain_outflow_on_mask(np.array([[signed]]), np.array([True]))


def _from_calibration_release(signed, **_):
    return float(_positive_release_by_cell(np.array([signed]), n_cells=None)[0])


# One row per site that applies the sign again. Each is called with a signed value in the sign of
# the aquifer and answers the water that leaves the aquifer.
_SITES = [
    pytest.param(_from_flux_module, id="core_budget_flux"),
    pytest.param(_from_mf6_budget, id="modflow6_budget"),
    pytest.param(_from_sfr, id="modflow6_sfr_exchange"),
    pytest.param(_from_lake, id="modflow6_lake_exchange"),
    pytest.param(_from_nwt, id="modflow_nwt_budget"),
    pytest.param(_from_boussinesq, id="boussinesq_budget"),
    pytest.param(_from_calibration_drain, id="calibration_drain_outflow"),
    pytest.param(_from_calibration_release, id="calibration_release"),
]


@pytest.mark.parametrize("site", _SITES)
@pytest.mark.parametrize(("signed", "outflow"), list(zip(_SIGNED, _OUTFLOW, strict=True)))
def test_every_site_same_outflow(site, signed, outflow, tmp_path, monkeypatch) -> None:
    result = site(signed, tmp_path=tmp_path, monkeypatch=monkeypatch)

    assert result == pytest.approx(outflow, abs=1e-18)
    assert result == pytest.approx(_from_flux_module(signed), abs=1e-18)


def _records(root: object) -> list[logging.LogRecord]:
    captured: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = captured.append  # type: ignore[method-assign]
    budget_flux.logger.addHandler(handler)
    try:
        warn_on_geometric_seepage_fallback(root, sim_id="sim-123")
    finally:
        budget_flux.logger.removeHandler(handler)
    return captured


def test_fallback_warning() -> None:
    captured = _records(_store(policy="consumers", kept_terms=["recharge"]))

    assert [record.levelno for record in captured] == [logging.WARNING]
    message = captured[0].getMessage()
    assert "sim-123" in message
    assert "surface_excess" in message
    assert "[simulation.results] keep_per_cell_budget = true" in message
    assert "spatial_fields" not in message


def test_non_mapping_root_ignored() -> None:
    assert _records(object()) == []


def _store(**budget_attrs: object) -> dict[str, object]:
    group = SimpleNamespace(attrs=dict(budget_attrs))
    return {SURFACE_EXCESS_STATE_GROUP: object(), "budget": group}


def test_consumers_store_message() -> None:
    (record,) = _records(_store(policy="consumers", kept_terms=["drain", "recharge"]))

    message = record.getMessage()
    assert "(drain, recharge)" in message
    assert "[simulation.results] keep_per_cell_budget = true" in message


def test_all_store_message() -> None:
    (record,) = _records(_store(policy="all", kept_terms=["recharge"]))

    message = record.getMessage()
    assert "produced no surface excess" in message
    assert "keep_per_cell_budget" not in message
