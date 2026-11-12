from __future__ import annotations

import ast
import inspect
import logging
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.optim.parameters import set_by_path
from hydromodpy.model.sinks_sources.etp import FlowEtpConfig
from hydromodpy.solver.modflow6 import build as build_module
from hydromodpy.solver.modflow6.builders import recharge
from hydromodpy.solver.modflow6.builders.recharge import (
    ETP_IGNORED_OUTSIDE_SOIL_MODE,
    RECHARGE_BINARY_MIN_PERIODS,
    areal_layer_index,
    bind_soil_etp_from_flow,
    build_evt_stress_period_data,
    build_soil_evta_payload,
    evt_list_spd_to_array_payload,
    extract_evt_payload_2d,
    resolve_deferred_soil_etp,
)
from hydromodpy.solver.modflow6.support.computational_top import raised_cells
from hydromodpy.solver.modflow_common.sink_mask import closed_depression_mask
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.mf6_toy_models import toy_model
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


@pytest.mark.parametrize(
    ("recharge_2d", "expected_clipped", "expected_evt"),
    [
        pytest.param(
            {
                0: np.array([1.0e-6, -2.0e-6], dtype=float),
                1: np.array([-3.0e-6, 4.0e-6], dtype=float),
            },
            {
                0: np.array([1.0e-6, 0.0], dtype=float),
                1: np.array([0.0, 4.0e-6], dtype=float),
            },
            {
                0: np.array([0.0, 2.0e-6], dtype=float),
                1: np.array([3.0e-6, 0.0], dtype=float),
            },
            id="test_modflow6_extracts_evt_payload_from_negative_2d_recharge",
        ),
        pytest.param(
            {
                0: np.asarray([1.0, -2.0], dtype=float),
                1: np.asarray([-3.0, 4.0], dtype=float),
            },
            {
                0: np.asarray([1.0, 0.0], dtype=float),
                1: np.asarray([0.0, 4.0], dtype=float),
            },
            {
                0: np.asarray([0.0, 2.0], dtype=float),
                1: np.asarray([3.0, 0.0], dtype=float),
            },
            id="test_modflow6_flow_adapter_extracts_evt_payload_from_negative_2d_recharge",
        ),
    ],
)
def test_modflow6_extracts_evt_payload_from_negative_2d_recharge(
    recharge_2d: dict[int, np.ndarray],
    expected_clipped: dict[int, np.ndarray],
    expected_evt: dict[int, np.ndarray],
) -> None:
    # All transient: each period keeps its own positive/negative split (H5 fix).
    clipped_rch, evt_data = extract_evt_payload_2d(
        recharge_2d, True, steady=[False, False], durations=[1.0, 1.0]
    )

    assert evt_data is not None
    np.testing.assert_allclose(clipped_rch[0], expected_clipped[0])
    np.testing.assert_allclose(clipped_rch[1], expected_clipped[1])
    np.testing.assert_allclose(evt_data[0], expected_evt[0])
    np.testing.assert_allclose(evt_data[1], expected_evt[1])


def test_modflow6_builds_evt_stress_period_data_from_routed_payload() -> None:
    model = toy_model()
    model._evt_rate_payload = {0: 0.0, 1: 1.0e-6}
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    botm_2d = np.array([[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]], dtype=float)
    solver_mesh = solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=3,
        top=top,
        botm=np.stack([botm_2d]),
    )

    evt_spd = build_evt_stress_period_data(
        model,
        solver_mesh,
        ocean_support_mask=np.zeros(6, dtype=bool),
        stream_support_mask=np.zeros(6, dtype=bool),
    )

    assert evt_spd is not None
    assert evt_spd[0] == []
    assert len(evt_spd[1]) == 6
    assert evt_spd[1][0] == [
        0,
        0,
        pytest.approx(10.0),
        pytest.approx(1.0e-6),
        pytest.approx(1.0),
    ]


def test_evt_list_spd_to_array_payload_matches_list_rates() -> None:
    """The array payload reproduces the list rates exactly when every record is layer 0."""
    top = np.array([50.0, 51.0, 52.0, 53.0], dtype=float)
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
        expected = np.zeros(4, dtype=float)
        for record in records:
            expected[int(record[1])] = float(record[3])
        assert np.array_equal(rate_by_period[kper], expected)


def test_evt_list_spd_to_array_payload_falls_back_on_lower_layer() -> None:
    """A record on a non-top layer forces the caller to keep the list package."""
    top = np.array([50.0, 51.0], dtype=float)
    evt_spd = {0: [[1, 0, 50.0, 2.0e-6, 1.0]]}

    assert evt_list_spd_to_array_payload(evt_spd, top_flat=top, ncpl=2) is None


# A calibration trial's extinction_depth reaches the built soil EVT package.
#
# ``extinction_depth`` is now declared ``Calibrable`` on ``FlowEtpConfig``
# (``hydromodpy/model/sinks_sources/etp.py``). A trial writes it the same
# way any other replace-mode parameter is written, through
# ``hydromodpy.calibration.optim.parameters.set_by_path``, on the typed config a
# ``TrialContext.fork`` rebuilds the runtime ``Flow`` from before every trial
# solve. ``bind_soil_etp_from_flow`` then reads it straight off that config, so
# no solve is needed to prove the wiring: only the MODFLOW 6 soil-mode builder
# that turns it into the EVTA payload.

_NCPL = 4


def _mesh() -> SolverMesh:
    top = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    botm = np.array([[1.0, 1.0], [1.0, 1.0]], dtype=float)
    return solver_mesh_from_structured_arrays(nrow=2, ncol=2, top=top, botm=np.stack([botm]))


def _soil_mode_model(etp_cfg: FlowEtpConfig) -> SimpleNamespace:
    """Bind ``etp_cfg`` the way MODFLOW 6 soil mode does, with the real binder."""
    model = SimpleNamespace(
        inputs=make_model(active_sinks_sources=("etp",), etp=etp_cfg),
        ncpl=_NCPL,
        nper=1,
        model_name_mf6="m",
        drain_band_depth_m=0.0,
    )
    bind_soil_etp_from_flow(model)
    # ``resolve_deferred_soil_etp`` discretizes the heterogeneous source onto
    # the grid; out of scope here (exercised by the soil EVT rate tests), so
    # the rate is set directly, the way those tests also do.
    model._soil_etp_rate = {0: np.full(_NCPL, 1.0e-8)}
    return model


def _trial_etp(base: FlowEtpConfig, trial_value: float) -> FlowEtpConfig:
    """Copy ``base`` and write ``extinction_depth`` the way a trial does."""
    trial_cfg = base.model_copy(deep=True)
    set_by_path(trial_cfg, "extinction_depth", trial_value)
    return trial_cfg


def _base_etp() -> FlowEtpConfig:
    cfg = FlowEtpConfig(extinction_depth=1.0, heterogeneous_source=object())
    cfg._from_soil_reservoir = True
    return cfg


def test_a_trial_value_rebuilds_the_evt_depth() -> None:
    trial_cfg = _trial_etp(_base_etp(), 7.5)

    model = _soil_mode_model(trial_cfg)
    payload = build_soil_evta_payload(
        model,
        _mesh(),
        ocean_support_mask=np.zeros(_NCPL, dtype=bool),
        stream_support_mask=np.zeros(_NCPL, dtype=bool),
        lake_cell_ids=[],
        drain_active=False,
        shared_dir=None,
    )

    assert payload is not None
    _rate_payload, _surface, depth = payload
    assert depth == pytest.approx(7.5)


def test_two_trials_move_the_depth_each_time() -> None:
    """The builder is not caching the first trial's depth."""
    base = _base_etp()
    depths = []
    for trial_value in (2.0, 12.0):
        model = _soil_mode_model(_trial_etp(base, trial_value))
        _rate, _surface, depth = build_soil_evta_payload(
            model,
            _mesh(),
            ocean_support_mask=np.zeros(_NCPL, dtype=bool),
            stream_support_mask=np.zeros(_NCPL, dtype=bool),
            lake_cell_ids=[],
            drain_active=False,
            shared_dir=None,
        )
        depths.append(depth)

    assert depths == [pytest.approx(2.0), pytest.approx(12.0)]


# The soil residual ETP and a routed negative-recharge deficit never share EVT.
#
# Soil mode refuses ``[data.recharge]`` at load (R1), so ``build_soil_evta_payload``
# and ``build_evt_stress_period_data`` returning non-``None`` together should never
# happen; ``run_pre_processing`` raises instead of building one EVT package on top
# of the other. This is a source-shape test (like
# ``test_constant_head_roles.py::test_the_output_stem_is_settled_before_any_file_is_named_after_it``):
# the guard sits in a single ``noqa: PLR0915`` function no unit test calls whole.


def _soil_evta_guard(tree: ast.AST) -> ast.If:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "soil_evta"
    )


def test_both_payloads_present_raises_before_either_package_is_built() -> None:
    tree = ast.parse(inspect.getsource(recharge.build_recharge_and_evt))
    outer = _soil_evta_guard(tree)

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


# A long soil-ETP chronicle is externalized to binary EVTA files, like RCHA.
#
# Above the binary threshold FloPy would format every value of every period by
# hand; ``build_soil_evta_payload`` routes the rate through
# ``externalize_recharge_spd(..., package="evta")`` instead, same as recharge does
# for RCHA.

_NPER = RECHARGE_BINARY_MIN_PERIODS + 6


def _model() -> SimpleNamespace:
    rng = np.random.default_rng(0)
    rate = {kper: rng.uniform(1.0e-9, 1.0e-8, size=_NCPL) for kper in range(_NPER)}
    return SimpleNamespace(
        ncpl=_NCPL,
        nper=_NPER,
        model_name_mf6="m",
        drain_band_depth_m=0.0,
        _soil_etp_rate=rate,
        _soil_evt_surface_offset_m=0.0,
        _soil_evt_extinction_depth_m=1.0,
    )


def _build(model: SimpleNamespace, *, shared_dir: str | None):
    return build_soil_evta_payload(
        model,
        _mesh(),
        ocean_support_mask=np.zeros(_NCPL, dtype=bool),
        stream_support_mask=np.zeros(_NCPL, dtype=bool),
        lake_cell_ids=[],
        drain_active=False,
        shared_dir=shared_dir,
    )


def test_per_model_files_are_named_after_the_evta_package() -> None:
    payload = _build(_model(), shared_dir=None)

    assert payload is not None
    rate, _, _ = payload
    assert set(rate) == set(range(_NPER))
    for kper, record in rate.items():
        assert record["filename"] == f"m.evta.{kper}.bin"
        assert "data" in record


# The soil EVTA rate is zeroed exactly where LAK or a CHD already own the flux.
#
# An inactive (fixed-area) lake cell gets its open-water evaporation from LAK;
# an ocean or stream CHD cell never receives MF6 ET at all (``ibound < 0``). Both
# must read 0 in the EVTA rate array, and every other cell keeps the soil's
# discretized deficit.

_NROW, _NCOL = 2, 3


_NCPL_4 = _NROW * _NCOL


def _mesh_4() -> SolverMesh:
    top = np.full((_NROW, _NCOL), 10.0)
    botm = np.full((_NROW, _NCOL), 0.0)
    return solver_mesh_from_structured_arrays(
        nrow=_NROW, ncol=_NCOL, top=top, botm=np.stack([botm])
    )


def _model_4() -> SimpleNamespace:
    return SimpleNamespace(
        ncpl=_NCPL_4,
        nper=1,
        model_name_mf6="m",
        drain_band_depth_m=0.0,
        _soil_etp_rate={0: np.full(_NCPL_4, 2.0e-8)},
        _soil_evt_surface_offset_m=0.0,
        _soil_evt_extinction_depth_m=1.0,
    )


def test_lake_ocean_and_stream_cells_draw_no_evta() -> None:
    ocean_mask = np.zeros(_NCPL_4, dtype=bool)
    ocean_mask[0] = True
    stream_mask = np.zeros(_NCPL_4, dtype=bool)
    stream_mask[3] = True
    lake_cell_ids = [5]

    payload = build_soil_evta_payload(
        _model_4(),
        _mesh_4(),
        ocean_support_mask=ocean_mask,
        stream_support_mask=stream_mask,
        lake_cell_ids=lake_cell_ids,
        drain_active=False,
        shared_dir=None,
    )

    assert payload is not None
    rate, _, _ = payload
    rate0 = rate[0]
    assert rate0[0] == 0.0
    assert rate0[3] == 0.0
    assert rate0[5] == 0.0
    np.testing.assert_allclose(rate0[[1, 2, 4]], 2.0e-8)


def test_without_any_excluded_cell_every_cell_keeps_the_soil_rate() -> None:
    payload = build_soil_evta_payload(
        _model_4(),
        _mesh_4(),
        ocean_support_mask=np.zeros(_NCPL_4, dtype=bool),
        stream_support_mask=np.zeros(_NCPL_4, dtype=bool),
        lake_cell_ids=[],
        drain_active=False,
        shared_dir=None,
    )

    assert payload is not None
    rate, _, _ = payload
    np.testing.assert_allclose(rate[0], np.full(_NCPL_4, 2.0e-8))


# The soil EVTA surface tracks the DRN elevation, not always the raw top.
#
# The soil reservoir has already taken the ETP it could, so what the EVT package
# draws is what would otherwise reach the drain: the same elevation the DRN
# builder gives the cell (``drain_discharge_band``), lowered further by
# ``surface_offset`` when the file asks for it.


def _model_5(*, drain_band_depth_m: float, surface_offset_m: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        ncpl=_NCPL,
        nper=1,
        model_name_mf6="m",
        drain_band_depth_m=drain_band_depth_m,
        _soil_etp_rate={0: np.full(_NCPL, 1.0e-8)},
        _soil_evt_surface_offset_m=surface_offset_m,
        _soil_evt_extinction_depth_m=1.0,
    )


def _surface(model: SimpleNamespace, *, drain_active: bool) -> np.ndarray:
    mesh = _mesh()
    payload = build_soil_evta_payload(
        model,
        mesh,
        ocean_support_mask=np.zeros(_NCPL, dtype=bool),
        stream_support_mask=np.zeros(_NCPL, dtype=bool),
        lake_cell_ids=[],
        drain_active=drain_active,
        shared_dir=None,
    )
    assert payload is not None
    _, surface, _ = payload
    return surface


def test_a_zero_band_depth_leaves_the_surface_at_the_top() -> None:
    model = _model_5(drain_band_depth_m=0.0)
    surface = _surface(model, drain_active=True)
    np.testing.assert_allclose(surface, [10.0, 11.0, 12.0, 13.0])


def test_a_one_metre_band_lowers_the_surface_by_half_the_band() -> None:
    model = _model_5(drain_band_depth_m=1.0)
    surface = _surface(model, drain_active=True)
    np.testing.assert_allclose(surface, [9.5, 10.5, 11.5, 12.5])


def test_an_inactive_drain_leaves_the_surface_at_the_top() -> None:
    model = _model_5(drain_band_depth_m=1.0)
    surface = _surface(model, drain_active=False)
    np.testing.assert_allclose(surface, [10.0, 11.0, 12.0, 13.0])


def test_a_surface_offset_lowers_the_surface_further() -> None:
    model = _model_5(drain_band_depth_m=0.0, surface_offset_m=0.3)
    surface = _surface(model, drain_active=True)
    np.testing.assert_allclose(surface, np.array([10.0, 11.0, 12.0, 13.0]) - 0.3)


# A project like the atelier Nancon one gains no EVT package.
#
# Its ``project.toml`` loads ``[data.etp]`` and lists ``"etp"`` in
# ``flow.active_sinks_sources``, exactly what MODFLOW-NWT reads for EVT; under
# MODFLOW 6, without ``[flow.sinks_sources.recharge.soil]``, that ETP must still
# go nowhere (only the warning is new).


def test_a_loaded_etp_without_the_soil_marker_reaches_no_evta_package(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # SIM2 ETP loaded like [data.etp] would, same as an ordinary NWT EVT source.
    etp_cfg = SimpleNamespace(from_soil_reservoir=False, heterogeneous_source=object())
    model = SimpleNamespace(
        inputs=make_model(
            active_sinks_sources=(
                "recharge",
                "etp",
            ),
            etp=etp_cfg,
        ),
        ncpl=_NCPL,
        nper=1,
        model_name_mf6="atelier",
        drain_band_depth_m=0.0,
        solver_mesh=_mesh(),
    )

    with caplog.at_level(logging.WARNING):
        bind_soil_etp_from_flow(model)
        resolve_deferred_soil_etp(model)

    assert model._soil_etp_rate is None
    assert ETP_IGNORED_OUTSIDE_SOIL_MODE in caplog.text

    payload = build_soil_evta_payload(
        model,
        model.solver_mesh,
        ocean_support_mask=np.zeros(_NCPL, dtype=bool),
        stream_support_mask=np.zeros(_NCPL, dtype=bool),
        lake_cell_ids=[],
        drain_active=False,
        shared_dir=None,
    )

    assert payload is None


# MODFLOW 6 draws ETP from the water table only when the soil marked it.
#
# Outside soil mode ``"etp"`` in ``flow.active_sinks_sources`` has never driven a
# MODFLOW 6 package: this stays true, with one warning added so a project that
# lists it is not silently ignored.


class _Quantity:
    """Minimal stand-in for the pint quantity ``surface_offset`` holds."""

    def __init__(self, magnitude: float) -> None:
        self._magnitude = magnitude

    def to(self, unit: str) -> _Quantity:
        assert unit == "m"
        return self

    @property
    def magnitude(self) -> float:
        return self._magnitude


def _model_7(*, active: list[str], etp_cfg: object | None) -> SimpleNamespace:
    return SimpleNamespace(inputs=make_model(active_sinks_sources=tuple(active), etp=etp_cfg))


def test_an_unmarked_etp_is_ignored_and_warned_about(caplog: pytest.LogCaptureFixture) -> None:
    etp_cfg = SimpleNamespace(from_soil_reservoir=False, heterogeneous_source="a grid")
    model = _model_7(active=["etp"], etp_cfg=etp_cfg)

    with caplog.at_level(logging.WARNING):
        bind_soil_etp_from_flow(model)

    assert model._soil_etp_source is None
    assert ETP_IGNORED_OUTSIDE_SOIL_MODE in caplog.text


def test_the_soil_marked_etp_is_bound(caplog: pytest.LogCaptureFixture) -> None:
    source = object()
    etp_cfg = SimpleNamespace(
        from_soil_reservoir=True,
        heterogeneous_source=source,
        interpolation_method="linear",
        surface_offset=_Quantity(0.3),
        extinction_depth=1.5,
    )
    model = _model_7(active=["etp"], etp_cfg=etp_cfg)

    with caplog.at_level(logging.WARNING):
        bind_soil_etp_from_flow(model)

    assert model._soil_etp_source is source
    assert model._soil_etp_interpolation_method == "linear"
    assert model._soil_evt_surface_offset_m == pytest.approx(0.3)
    assert model._soil_evt_extinction_depth_m == pytest.approx(1.5)
    assert ETP_IGNORED_OUTSIDE_SOIL_MODE not in caplog.text


def test_an_inactive_etp_binds_nothing_and_warns_nothing(caplog: pytest.LogCaptureFixture) -> None:
    etp_cfg = SimpleNamespace(from_soil_reservoir=True, heterogeneous_source=object())
    model = _model_7(active=[], etp_cfg=etp_cfg)

    with caplog.at_level(logging.WARNING):
        bind_soil_etp_from_flow(model)

    assert model._soil_etp_source is None
    assert caplog.text == ""


def test_a_soil_marked_etp_without_its_grid_is_a_bug() -> None:
    etp_cfg = SimpleNamespace(from_soil_reservoir=True, heterogeneous_source=None)
    model = _model_7(active=["etp"], etp_cfg=etp_cfg)

    with pytest.raises(RuntimeError, match="without its grid"):
        bind_soil_etp_from_flow(model)


# RCHA and EVTA name the top active layer only when a pass-through cell needs it.
#
# MODFLOW 6 moves the flux of an inactive top cell down by itself and drops the
# flux of a pass-through cell. A stack without pass-through cell writes no layer
# array, so its files do not change.


def _mesh_8(idomain: np.ndarray) -> SolverMesh:
    top = np.full(4, 100.0)
    botm = np.vstack([np.full(4, 90.0), np.full(4, 80.0), np.full(4, 70.0)])
    mesh = solver_mesh_from_structured_arrays(nrow=2, ncol=2, top=top, botm=botm)
    return SolverMesh(cell_mesh=mesh.cell_mesh, top=mesh.top, botm=mesh.botm, idomain=idomain)


def test_a_stack_without_pass_through_cell_writes_no_layer_array() -> None:
    idomain = np.ones((3, 4), dtype=int)
    idomain[0, 1] = 0

    assert areal_layer_index(_mesh_8(idomain)) is None


def test_a_pass_through_cell_sends_the_flux_to_the_top_active_layer() -> None:
    idomain = np.ones((3, 4), dtype=int)
    idomain[0, 1] = -1
    idomain[:2, 2] = [0, -1]
    idomain[:, 3] = 0

    np.testing.assert_array_equal(areal_layer_index(_mesh_8(idomain)), [0, 1, 2, 0])


# Drains, evapotranspiration, the computational top and the sink mask read the top active cell.
#
# Under a stack whose top layer is inactive in a column (a pinched or voxel
# layer), the surface processes act on the first active cell below. A lake
# footprint stays closed: LAK owns its surface.

N_CELLS = 4


TOP = np.array([10.0, 9.0, 8.0, 7.0])


BOTM = np.vstack([TOP - 3.0, TOP - 10.0])


def _mesh_9(idomain: np.ndarray) -> SolverMesh:
    base = solver_mesh_from_structured_arrays(nrow=1, ncol=N_CELLS, top=TOP, botm=BOTM)
    return SolverMesh(cell_mesh=base.cell_mesh, top=base.top, botm=base.botm, idomain=idomain)


def _drain_model(mesh: SolverMesh, covered=()) -> SimpleNamespace:
    return SimpleNamespace(
        dem_mask=mesh.closed_surface(covered),
        nper=1,
        ncpl=N_CELLS,
        hk=np.vstack([np.full(N_CELLS, 1e-4), np.full(N_CELLS, 1e-5)]),
        sink_fill=False,
        sink=None,
        drain_band_depth_m=0.0,
        drain_bed_thickness_m=1.0,
        drain_conductance_floor_m2_s=1e-12,
    )


def test_only_a_column_whose_top_active_cell_is_in_layer_zero_is_raised() -> None:
    mesh = _mesh_9(np.array([[1, 0, 1, 1], [1, 1, 1, 1]]))
    assert raised_cells(mesh, open_water_cell_ids=[3]).tolist() == [True, False, True, False]


def test_a_covered_column_is_closed_to_the_sink_flood() -> None:
    top = np.full(9, 10.0)
    top[4] = 5.0
    base = solver_mesh_from_structured_arrays(nrow=3, ncol=3, top=top, botm=top - 20.0)
    # The center is a pit ringed by higher cells; covered by a lake, it is no pit.
    assert np.flatnonzero(closed_depression_mask(base)).tolist() == [4]
    assert not closed_depression_mask(base, covered_cells=[4]).any()
