"""Evapotranspiration (EVT and EVTA) payloads of the MODFLOW 6 recharge builder.

Rates are in m/s, depths and elevations in m. A deficit routed from negative
recharge becomes a list of EVT records, or an array payload when every kept cell
sits on layer 0. The soil residual ETP becomes an EVTA payload of its own.
"""

from __future__ import annotations

import ast
import inspect
import logging
import warnings
from types import SimpleNamespace

import flopy
import numpy as np
import pytest

from hydromodpy.calibration.optim.parameters import set_by_path
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.model.sinks_sources.etp import FlowEtpConfig
from hydromodpy.solver.modflow6.builders import recharge
from hydromodpy.solver.modflow6.builders.boundary_conditions import collapse_identical_periods
from hydromodpy.solver.modflow6.builders.recharge import (
    ETP_IGNORED_OUTSIDE_SOIL_MODE,
    RECHARGE_BINARY_MIN_PERIODS,
    areal_layer_index,
    bind_soil_etp_from_flow,
    build_evt_array_stress_period_data,
    build_evt_stress_period_data,
    build_recharge_and_evt,
    build_soil_evta_payload,
    evt_list_spd_to_array_payload,
    evt_routing_is_layer0_only,
    extract_evt_payload_2d,
    resolve_deferred_soil_etp,
)
from hydromodpy.solver.modflow6.modflow6_config import _coerce_modflow6_config
from hydromodpy.solver.modflow6.support.computational_top import raised_cells
from hydromodpy.solver.modflow_common.sink_mask import closed_depression_mask
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.mf6_toy_models import toy_model
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from, solver_mesh_from_structured_arrays


def plate(nrow: int, ncol: int, top) -> SolverMesh:
    """One layer, bottom at 1 m, a given top (m)."""
    top = np.asarray(top, dtype=float).reshape(nrow, ncol)
    return solver_mesh_from_structured_arrays(
        nrow=nrow, ncol=ncol, top=top, botm=np.stack([np.ones_like(top)])
    )


def plate_2x3() -> SolverMesh:
    return plate(2, 3, [[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]])


def plate_2x2() -> SolverMesh:
    return plate(2, 2, [[10.0, 11.0], [12.0, 13.0]])


def three_layer_stack(idomain: np.ndarray) -> SolverMesh:
    top = np.full(4, 100.0)
    botm = np.vstack([np.full(4, 90.0), np.full(4, 80.0), np.full(4, 70.0)])
    mesh = solver_mesh_from_structured_arrays(nrow=2, ncol=2, top=top, botm=botm)
    return SolverMesh(cell_mesh=mesh.cell_mesh, top=mesh.top, botm=mesh.botm, idomain=idomain)


def two_layer_row(inactive_mask: np.ndarray) -> SolverMesh:
    vertices = np.array(
        [[0, 0], [1, 0], [2, 0], [3, 0], [0, 1], [1, 1], [2, 1], [3, 1]], dtype=float
    )
    conn = np.array([[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6]], dtype=int)
    return solver_mesh_from(
        HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),)),
        top=np.full(3, 10.0),
        botm=np.array([[5.0, 5.0, 5.0], [0.0, 0.0, 0.0]]),
        inactive_mask=inactive_mask,
    )


def soil_model(
    *, ncpl=4, rate=1.0e-8, nper=1, band_m=0.0, offset_m=0.0, depth_m=1.0
) -> SimpleNamespace:
    """A model whose soil ETP rate (m/s) is already discretized on the grid."""
    rates = rate if isinstance(rate, dict) else {k: np.full(ncpl, rate) for k in range(nper)}
    return SimpleNamespace(
        ncpl=ncpl,
        nper=nper,
        model_name_mf6="m",
        drain_band_depth_m=band_m,
        _soil_etp_rate=rates,
        _soil_evt_surface_offset_m=offset_m,
        _soil_evt_extinction_depth_m=depth_m,
    )


def soil_payload(
    model, mesh, *, ocean=(), stream=(), lakes=(), drain_active=False, shared_dir=None
):
    ncpl = model.ncpl
    ocean_mask, stream_mask = np.zeros(ncpl, dtype=bool), np.zeros(ncpl, dtype=bool)
    ocean_mask[list(ocean)] = True
    stream_mask[list(stream)] = True
    return build_soil_evta_payload(
        model,
        mesh,
        ocean_support_mask=ocean_mask,
        stream_support_mask=stream_mask,
        lake_cell_ids=list(lakes),
        drain_active=drain_active,
        shared_dir=shared_dir,
    )


def flow_with_etp(active: list[str], etp_cfg: object | None) -> SimpleNamespace:
    return SimpleNamespace(inputs=make_model(active_sinks_sources=tuple(active), etp=etp_cfg))


class Quantity:
    """Minimal stand-in for the pint quantity that surface_offset holds."""

    def __init__(self, magnitude: float) -> None:
        self.magnitude = magnitude

    def to(self, unit: str) -> Quantity:
        assert unit == "m"
        return self


EVT_PAYLOADS = [
    pytest.param(
        {0: [1.0e-6, -2.0e-6], 1: [-3.0e-6, 4.0e-6]},
        {0: [1.0e-6, 0.0], 1: [0.0, 4.0e-6]},
        {0: [0.0, 2.0e-6], 1: [3.0e-6, 0.0]},
        id="rates in m/s",
    ),
    pytest.param(
        {0: [1.0, -2.0], 1: [-3.0, 4.0]},
        {0: [1.0, 0.0], 1: [0.0, 4.0]},
        {0: [0.0, 2.0], 1: [3.0, 0.0]},
        id="values of order one",
    ),
]


@pytest.mark.parametrize(("recharge_2d", "expected_clipped", "expected_evt"), EVT_PAYLOADS)
def test_evt_from_negative_recharge(recharge_2d, expected_clipped, expected_evt) -> None:
    # All transient: each period keeps its own positive and negative split.
    recharge_2d = {k: np.asarray(v, dtype=float) for k, v in recharge_2d.items()}
    clipped_rch, evt_data = extract_evt_payload_2d(
        recharge_2d, True, steady=[False, False], durations=[1.0, 1.0]
    )

    assert evt_data is not None
    for kper in (0, 1):
        np.testing.assert_allclose(clipped_rch[kper], expected_clipped[kper])
        np.testing.assert_allclose(evt_data[kper], expected_evt[kper])


def test_evt_records() -> None:
    model = toy_model()
    model._evt_rate_payload = {0: 0.0, 1: 1.0e-6}

    evt_spd = build_evt_stress_period_data(
        model,
        plate_2x3(),
        ocean_support_mask=np.zeros(6, dtype=bool),
        stream_support_mask=np.zeros(6, dtype=bool),
    )

    # A record is [layer, cell, surface m, rate m/s, extinction depth m].
    assert evt_spd is not None
    assert evt_spd[0] == []
    assert len(evt_spd[1]) == 6
    assert evt_spd[1][0] == [0, 0, pytest.approx(10.0), pytest.approx(1.0e-6), pytest.approx(1.0)]


def test_array_payload_rates() -> None:
    top = np.array([50.0, 51.0, 52.0, 53.0])
    evt_spd = {
        0: [[0, 1, 51.0, 2.0e-6, 1.0], [0, 3, 53.0, 4.0e-6, 1.0]],
        2: [[0, 1, 51.0, 5.0e-6, 1.0]],
    }

    payload = evt_list_spd_to_array_payload(evt_spd, top_flat=top, ncpl=4)

    assert payload is not None
    rate_by_period, surface, depth = payload
    assert depth == pytest.approx(1.0)
    assert np.array_equal(surface, top)
    assert set(rate_by_period) == {0, 2}
    for kper, records in evt_spd.items():
        expected = np.zeros(4)
        for record in records:
            expected[int(record[1])] = float(record[3])
        assert np.array_equal(rate_by_period[kper], expected)


def test_array_payload_lower_layer() -> None:
    # A record on a lower layer forces the caller to keep the list package.
    evt_spd = {0: [[1, 0, 50.0, 2.0e-6, 1.0]]}

    assert evt_list_spd_to_array_payload(evt_spd, top_flat=np.array([50.0, 51.0]), ncpl=2) is None


def reference_array_payload(model, mesh, *, ocean_mask, stream_mask, lake_cell_ids=()):
    """The list, collapse, array chain. The vectorized build must equal it byte for byte."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        evt_spd = build_evt_stress_period_data(
            model,
            mesh,
            ocean_support_mask=ocean_mask,
            stream_support_mask=stream_mask,
            lake_cell_ids=lake_cell_ids,
        )
    if evt_spd is None:
        return None
    evt_spd = collapse_identical_periods(evt_spd)
    return evt_list_spd_to_array_payload(evt_spd, top_flat=mesh.top, ncpl=int(model.ncpl))


def test_vectorized_matches_list_path() -> None:
    model = toy_model()
    model.nper = 5
    model.steady = np.array([True, False, False, False, False])
    mesh = plate_2x3()

    # Cell layout (row-major, 2x3): 0 1 2 / 3 4 5. Kept cells are 0, 1 and 3.
    ocean_mask = np.array([False, False, True, False, False, False])
    stream_mask = np.array([False, False, False, False, False, True])
    lake_cell_ids = [4]

    busy = np.array([1.0e-6, 2.0e-6, 0.0, 0.0, 5.0e-6, 0.0])
    model._evt_rate_payload = {
        # Steady period. Cell 1 is kept but its rate is not positive, so no record.
        0: np.array([5.0e-7, 0.0, 9.0e-7, 3.0e-7, 9.0e-7, 9.0e-7]),
        1: busy,
        # No deficit anywhere, a real change point against period 1.
        2: np.zeros(6),
        3: busy,
        # Repeats period 3, so collapsing drops it.
        4: busy,
    }
    masks = {"ocean_support_mask": ocean_mask, "stream_support_mask": stream_mask}
    assert evt_routing_is_layer0_only(model, mesh, lake_cell_ids=lake_cell_ids, **masks)

    reference = reference_array_payload(
        model, mesh, ocean_mask=ocean_mask, stream_mask=stream_mask, lake_cell_ids=lake_cell_ids
    )
    assert reference is not None
    ref_rate_by_period, ref_surface, ref_depth = reference

    with pytest.warns(RuntimeWarning, match="fixed EVT extinction depth"):
        vectorized = build_evt_array_stress_period_data(
            model, mesh, lake_cell_ids=lake_cell_ids, **masks
        )
    assert vectorized is not None
    vec_rate_by_period, vec_surface, vec_depth = vectorized

    assert vec_depth == pytest.approx(ref_depth)
    assert np.array_equal(vec_surface, ref_surface)
    # Change points only. Period 2 is kept although it carries no deficit.
    assert set(vec_rate_by_period) == set(ref_rate_by_period) == {0, 1, 2, 3}
    for kper, expected in ref_rate_by_period.items():
        assert np.array_equal(vec_rate_by_period[kper], expected)

    # Masked and non-positive cells never carry a rate.
    for rate in vec_rate_by_period.values():
        assert rate[2] == 0.0  # ocean
        assert rate[4] == 0.0  # lake
        assert rate[5] == 0.0  # stream
    assert vec_rate_by_period[0][1] == 0.0


def test_vectorized_depth_floor() -> None:
    model = toy_model()
    model.nper = 1
    model.steady = np.array([False])
    model.modflow_config = _coerce_modflow6_config(
        {"process_specific": {"evt_extinction_depth": 1.0e-10}}
    )
    model._evt_rate_payload = {0: 1.0e-6}
    mesh = plate_2x3()
    masks = {
        "ocean_support_mask": np.zeros(6, dtype=bool),
        "stream_support_mask": np.zeros(6, dtype=bool),
    }

    assert evt_routing_is_layer0_only(model, mesh, **masks)
    reference = reference_array_payload(
        model,
        mesh,
        ocean_mask=masks["ocean_support_mask"],
        stream_mask=masks["stream_support_mask"],
    )
    assert reference is not None
    assert reference[2] == pytest.approx(1.0e-6)

    with pytest.warns(RuntimeWarning):
        vectorized = build_evt_array_stress_period_data(model, mesh, **masks)
    assert vectorized is not None
    assert vectorized[2] == pytest.approx(1.0e-6)


def test_vectorized_without_deficit() -> None:
    model = toy_model()
    model.nper = 2
    model.steady = np.array([False, False])
    mesh = plate_2x3()
    masks = {
        "ocean_support_mask": np.zeros(6, dtype=bool),
        "stream_support_mask": np.zeros(6, dtype=bool),
    }

    # No _evt_rate_payload attribute at all.
    assert build_evt_array_stress_period_data(model, mesh, **masks) is None

    # Payload present but never positive once masked: same None as the list path.
    model._evt_rate_payload = {0: np.zeros(6), 1: -np.ones(6)}
    assert build_evt_stress_period_data(model, mesh, **masks) is None
    assert build_evt_array_stress_period_data(model, mesh, **masks) is None


def test_vectorized_lower_layer() -> None:
    # Cell 0 is active in layer 0. Cell 1 is inactive there but active in layer 1.
    mesh = two_layer_row(np.array([[False, True, True], [False, False, True]]))
    model = toy_model()
    model.nper = 1
    model.ncpl = 3
    model._evt_rate_payload = {0: 1.0e-6}
    masks = {
        "ocean_support_mask": np.zeros(3, dtype=bool),
        "stream_support_mask": np.zeros(3, dtype=bool),
    }

    assert not evt_routing_is_layer0_only(model, mesh, **masks)

    # The list path still places EVT on layer 1 for cell 1.
    with pytest.warns(RuntimeWarning):
        evt_spd = build_evt_stress_period_data(model, mesh, **masks)
    assert evt_list_spd_to_array_payload(evt_spd, top_flat=mesh.top, ncpl=3) is None


def base_etp() -> FlowEtpConfig:
    cfg = FlowEtpConfig(extinction_depth=1.0, heterogeneous_source=object())
    cfg._from_soil_reservoir = True
    return cfg


def soil_depth_after_trial(trial_value: float) -> float:
    trial_cfg = base_etp().model_copy(deep=True)
    set_by_path(trial_cfg, "extinction_depth", trial_value)
    model = SimpleNamespace(
        inputs=make_model(active_sinks_sources=("etp",), etp=trial_cfg),
        ncpl=4,
        nper=1,
        model_name_mf6="m",
        drain_band_depth_m=0.0,
    )
    bind_soil_etp_from_flow(model)
    # The discretization of the source is tested elsewhere, so the rate is set here.
    model._soil_etp_rate = {0: np.full(4, 1.0e-8)}
    payload = soil_payload(model, plate_2x2())
    assert payload is not None
    return payload[2]


def test_trial_value_sets_depth() -> None:
    assert soil_depth_after_trial(7.5) == pytest.approx(7.5)


def test_two_trials_move_depth() -> None:
    # The builder does not cache the depth of the first trial.
    depths = [soil_depth_after_trial(value) for value in (2.0, 12.0)]

    assert depths == [pytest.approx(2.0), pytest.approx(12.0)]


def test_soil_and_routed_deficit_collide() -> None:
    # Soil mode refuses [data.recharge] at load, so both payloads together are a bug.
    # The guard sits in one long function no unit test calls whole, so read its source.
    tree = ast.parse(inspect.getsource(recharge.build_recharge_and_evt))
    outer = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "soil_evta"
    )

    inner = outer.body[0]
    assert isinstance(inner, ast.If), "soil_evta branch must check evt_spd first"
    assert isinstance(inner.test, ast.Compare)
    assert isinstance(inner.test.left, ast.Name)
    assert inner.test.left.id == "evt_spd"

    raise_stmt = inner.body[0]
    assert isinstance(raise_stmt, ast.Raise), "the collision must raise, not fall through"
    assert isinstance(raise_stmt.exc, ast.Call)
    assert raise_stmt.exc.func.id == "RuntimeError"
    message = ast.literal_eval(raise_stmt.exc.args[0])
    assert message == (
        "the soil residual ETP and the routed negative recharge both ask for "
        "the EVT package; soil mode refuses [data.recharge], so this state is "
        "a bug."
    )


def test_long_chronicle_is_binary() -> None:
    # Above the binary threshold FloPy would format every value by hand.
    nper = RECHARGE_BINARY_MIN_PERIODS + 6
    rng = np.random.default_rng(0)
    rate = {kper: rng.uniform(1.0e-9, 1.0e-8, size=4) for kper in range(nper)}

    payload = soil_payload(soil_model(rate=rate, nper=nper), plate_2x2())

    assert payload is not None
    rate_files, _, _ = payload
    assert set(rate_files) == set(range(nper))
    for kper, record in rate_files.items():
        assert record["filename"] == f"m.evta.{kper}.bin"
        assert "data" in record


SOIL_RATE_CELLS = [
    pytest.param({}, [], id="no exclusion"),
    # An open-water lake gets its evaporation from LAK, an ocean or stream CHD cell none from ET.
    pytest.param({"ocean": [0], "stream": [3], "lakes": [5]}, [0, 3, 5], id="ocean stream lake"),
]


@pytest.mark.parametrize(("exclusions", "excluded"), SOIL_RATE_CELLS)
def test_soil_rate_by_cell(exclusions, excluded) -> None:
    mesh = solver_mesh_from_structured_arrays(
        nrow=2, ncol=3, top=np.full((2, 3), 10.0), botm=np.zeros((1, 2, 3))
    )

    payload = soil_payload(soil_model(ncpl=6, rate=2.0e-8), mesh, **exclusions)

    assert payload is not None
    expected = np.full(6, 2.0e-8)
    expected[excluded] = 0.0
    np.testing.assert_allclose(payload[0][0], expected)


# The EVTA surface follows the DRN elevation (lowered by half the drain band),
# then drops by surface_offset when the file asks for it.
SURFACES = [
    pytest.param(0.0, 0.0, True, [10.0, 11.0, 12.0, 13.0], id="no band"),
    pytest.param(1.0, 0.0, True, [9.5, 10.5, 11.5, 12.5], id="one metre band"),
    pytest.param(1.0, 0.0, False, [10.0, 11.0, 12.0, 13.0], id="drain inactive"),
    pytest.param(0.0, 0.3, True, [9.7, 10.7, 11.7, 12.7], id="surface offset"),
]


@pytest.mark.parametrize(("band_m", "offset_m", "drain_active", "expected"), SURFACES)
def test_evta_surface(band_m, offset_m, drain_active, expected) -> None:
    model = soil_model(rate=1.0e-8, band_m=band_m, offset_m=offset_m)

    payload = soil_payload(model, plate_2x2(), drain_active=drain_active)

    assert payload is not None
    np.testing.assert_allclose(payload[1], expected)


def test_unmarked_etp_reaches_no_evta(caplog) -> None:
    # The ETP of a NWT project, loaded like [data.etp], must go nowhere under MODFLOW 6.
    etp_cfg = SimpleNamespace(from_soil_reservoir=False, heterogeneous_source=object())
    model = SimpleNamespace(
        inputs=make_model(active_sinks_sources=("recharge", "etp"), etp=etp_cfg),
        ncpl=4,
        nper=1,
        model_name_mf6="atelier",
        drain_band_depth_m=0.0,
        solver_mesh=plate_2x2(),
    )

    with caplog.at_level(logging.WARNING):
        bind_soil_etp_from_flow(model)
        resolve_deferred_soil_etp(model)

    assert model._soil_etp_rate is None
    assert ETP_IGNORED_OUTSIDE_SOIL_MODE in caplog.text
    assert soil_payload(model, model.solver_mesh) is None


def test_unmarked_etp_warns(caplog) -> None:
    etp_cfg = SimpleNamespace(from_soil_reservoir=False, heterogeneous_source="a grid")
    model = flow_with_etp(["etp"], etp_cfg)

    with caplog.at_level(logging.WARNING):
        bind_soil_etp_from_flow(model)

    assert model._soil_etp_source is None
    assert ETP_IGNORED_OUTSIDE_SOIL_MODE in caplog.text


def test_soil_etp_is_bound(caplog) -> None:
    source = object()
    etp_cfg = SimpleNamespace(
        from_soil_reservoir=True,
        heterogeneous_source=source,
        interpolation_method="linear",
        surface_offset=Quantity(0.3),
        extinction_depth=1.5,
    )
    model = flow_with_etp(["etp"], etp_cfg)

    with caplog.at_level(logging.WARNING):
        bind_soil_etp_from_flow(model)

    assert model._soil_etp_source is source
    assert model._soil_etp_interpolation_method == "linear"
    assert model._soil_evt_surface_offset_m == pytest.approx(0.3)
    assert model._soil_evt_extinction_depth_m == pytest.approx(1.5)
    assert ETP_IGNORED_OUTSIDE_SOIL_MODE not in caplog.text


def test_inactive_etp_binds_nothing(caplog) -> None:
    etp_cfg = SimpleNamespace(from_soil_reservoir=True, heterogeneous_source=object())
    model = flow_with_etp([], etp_cfg)

    with caplog.at_level(logging.WARNING):
        bind_soil_etp_from_flow(model)

    assert model._soil_etp_source is None
    assert caplog.text == ""


def test_soil_etp_without_grid() -> None:
    etp_cfg = SimpleNamespace(from_soil_reservoir=True, heterogeneous_source=None)

    with pytest.raises(RuntimeError, match="without its grid"):
        bind_soil_etp_from_flow(flow_with_etp(["etp"], etp_cfg))


def test_no_layer_array_without_pass_through() -> None:
    idomain = np.ones((3, 4), dtype=int)
    idomain[0, 1] = 0

    assert areal_layer_index(three_layer_stack(idomain)) is None


def test_pass_through_top_active_layer() -> None:
    idomain = np.ones((3, 4), dtype=int)
    idomain[0, 1] = -1
    idomain[:2, 2] = [0, -1]
    idomain[:, 3] = 0

    np.testing.assert_array_equal(areal_layer_index(three_layer_stack(idomain)), [0, 1, 2, 0])


def test_raised_cells() -> None:
    top = np.array([10.0, 9.0, 8.0, 7.0])
    base = solver_mesh_from_structured_arrays(
        nrow=1, ncol=4, top=top, botm=np.vstack([top - 3.0, top - 10.0])
    )
    mesh = SolverMesh(
        cell_mesh=base.cell_mesh,
        top=base.top,
        botm=base.botm,
        idomain=np.array([[1, 0, 1, 1], [1, 1, 1, 1]]),
    )

    assert raised_cells(mesh, open_water_cell_ids=[3]).tolist() == [True, False, True, False]


def test_covered_column_is_no_pit() -> None:
    top = np.full(9, 10.0)
    top[4] = 5.0
    base = solver_mesh_from_structured_arrays(nrow=3, ncol=3, top=top, botm=top - 20.0)
    # The center is a pit ringed by higher cells. Covered by a lake, it is no pit.
    assert np.flatnonzero(closed_depression_mask(base)).tolist() == [4]
    assert not closed_depression_mask(base, covered_cells=[4]).any()


def flow_model_on(mesh: SolverMesh, tmp_path, *, nper: int = 1, **members) -> SimpleNamespace:
    """The toy model moved onto *mesh*, with a flopy GWF and its DISV, ready for RCHA and EVT."""
    model = toy_model(**members)
    model.solver_mesh = mesh
    model.nper = nper
    model.ncpl = mesh.n_cells
    model.nlay = mesh.nlay
    model.perlen = np.full(nper, 86400.0)
    model.steady = np.zeros(nper, dtype=bool)
    model.model_name_mf6 = "m"
    model.recharge = 1.0e-8
    model.first_clim = "mean"
    model.drain_band_depth_m = 0.0
    model._lake_cell_ids = []
    model._evt_rate_payload = None
    model._soil_etp_rate = None
    sim = flopy.mf6.MFSimulation(sim_name="evt", sim_ws=str(tmp_path))
    flopy.mf6.ModflowTdis(sim, nper=nper, perioddata=[(86400.0, 1, 1.0)] * nper)
    model.gwf = flopy.mf6.ModflowGwf(sim, modelname="m")
    flopy.mf6.ModflowGwfdisv(model.gwf, nlay=mesh.nlay, **mesh.to_disv_kwargs())
    return model


def no_mask(model) -> np.ndarray:
    return np.zeros(model.ncpl, dtype=bool)


def test_rch_and_routed_evt_on_a_plate(tmp_path) -> None:
    # Lake cell 0 gets neither recharge nor EVT, the other five cells get both.
    model = flow_model_on(plate_2x3(), tmp_path)
    model._lake_cell_ids = [0]
    model._evt_rate_payload = {0: np.full(6, 2.0e-8)}

    with pytest.warns(RuntimeWarning, match="fixed EVT extinction depth"):
        build_recharge_and_evt(model, model.solver_mesh, no_mask(model), no_mask(model))

    np.testing.assert_allclose(model.rch.recharge.get_data(0), [0.0] + [1.0e-8] * 5)
    np.testing.assert_allclose(model.evt.rate.get_data(0), [0.0] + [2.0e-8] * 5)


def test_soil_etp_on_a_plate(tmp_path) -> None:
    model = flow_model_on(plate_2x3(), tmp_path)
    model._lake_cell_ids = [0]
    model._soil_etp_rate = {0: np.full(6, 1.0e-8)}
    model._soil_evt_surface_offset_m = 0.0
    model._soil_evt_extinction_depth_m = 2.5

    build_recharge_and_evt(model, model.solver_mesh, no_mask(model), no_mask(model))

    np.testing.assert_allclose(model.evt.rate.get_data(0), [0.0] + [1.0e-8] * 5)
    np.testing.assert_allclose(model.evt.depth.get_data(0), 2.5)


# Cell 0 is active in layer 0, cell 1 only in layer 1, cell 2 in none. A deficit on cell 1
# lands on layer 1 and keeps the list package, one only on cell 0 still fits an array.
LOWER_LAYER_DEFICITS = [
    pytest.param(
        np.asarray([1.0e-6, 2.0e-6, 3.0e-6]),
        "evt",
        [(0, 0), (1, 1)],
        id="deficit on a lower layer",
    ),
    pytest.param(np.asarray([1.0e-6, 0.0, 0.0]), "evta", None, id="deficit on layer 0 only"),
]


@pytest.mark.parametrize(("deficit", "package", "cells"), LOWER_LAYER_DEFICITS)
def test_routed_evt_with_a_lower_layer(tmp_path, deficit, package, cells) -> None:
    mesh = two_layer_row(np.array([[False, True, True], [False, False, True]]))
    model = flow_model_on(mesh, tmp_path)
    model._evt_rate_payload = {0: deficit}

    with pytest.warns(RuntimeWarning, match="fixed EVT extinction depth"):
        build_recharge_and_evt(model, mesh, no_mask(model), no_mask(model))

    assert model.evt.package_type == package
    if cells is not None:
        records = model.evt.stress_period_data.get_data(0)
        assert [tuple(int(i) for i in record[0]) for record in records] == [
            (0, 0), (1, 1)  # (layer, cell) of the two kept cells
        ]  # fmt: skip
        assert model.evt.maxbound.get_data() == 2
    else:
        np.testing.assert_allclose(model.evt.rate.get_data(0), [1.0e-6, 0.0, 0.0])


def test_no_evt_without_a_deficit() -> None:
    model = toy_model()
    model._evt_rate_payload = None
    masks = {
        "ocean_support_mask": np.zeros(6, dtype=bool),
        "stream_support_mask": np.zeros(6, dtype=bool),
    }

    assert build_evt_stress_period_data(model, model.solver_mesh, **masks) is None


def test_evt_array_needs_a_record() -> None:
    assert evt_list_spd_to_array_payload({0: []}, top_flat=np.full(3, 10.0), ncpl=3) is None


def test_soil_and_routed_deficit_are_refused_together(tmp_path) -> None:
    model = flow_model_on(plate_2x3(), tmp_path)
    model._soil_etp_rate = {0: np.full(6, 1.0e-8)}
    model._soil_evt_surface_offset_m = 0.0
    model._soil_evt_extinction_depth_m = 1.0
    model._evt_rate_payload = {0: np.full(6, 2.0e-8)}

    with pytest.raises(RuntimeError, match="both ask for the EVT package"):
        build_recharge_and_evt(model, model.solver_mesh, no_mask(model), no_mask(model))
