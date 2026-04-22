from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import hydromodpy.solver.modflow6.flow_to_modflow_adapter as mf6_flow_adapter
from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.physics.flow.boundary_conditions import FlowBoundaryConditionConfig
from hydromodpy.physics.flow.initial_conditions import (
    FlowInitialCondition,
    FlowInitialConditions,
)
from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig, FlowWellConfig
from hydromodpy.solver.modflow6 import Modflow6
from hydromodpy.solver.modflow_common.solver_mesh import SolverMesh
from hydromodpy.solver.utils.mesh.gmsh_grid import (
    GmshSupportMetadata,
    build_gmsh_support_metadata,
)
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh


class _DummyGeographic:
    def __init__(self, dem: np.ndarray):
        self.dem_res = 1.0
        self.xmin = 0.0
        self.ymax = float(dem.shape[0])
        self.dem_box_buff_data = np.asarray(dem, dtype=float)
        self.dem_data = np.asarray(dem, dtype=float)
        self.watershed_box_buff_dem = "dummy_box.tif"
        self.watershed_buff_dem = "dummy_buff.tif"


def _build_model() -> Modflow6:
    dem = np.array([[10.0, 10.0, 10.0], [10.0, 10.0, 10.0]], dtype=float)
    geo = _DummyGeographic(dem)
    model = Modflow6(geographic=geo, model_folder=".")
    model.nlay = 1
    model.nrow = 2
    model.ncol = 3
    model.ncpl = 6
    model.nper = 2
    model.dem_mask = np.zeros(6, dtype=bool)  # flat (ncpl,)
    model.time_grid = SimpleNamespace(
        window=ResolvedSimulationTimeWindow(
            start=pd.Timestamp("2003-01-01"),
            end=pd.Timestamp("2003-02-28"),
            step_value=1,
            step_unit="month",
            coverage_policy="error",
        )
    )
    return model


def _build_unstructured_runtime(
    *,
    river_internal_edge: bool = False,
    boundary_labels_by_edge_id: dict[int, str] | None = None,
) -> tuple[SolverMesh, GmshSupportMetadata]:
    vertices = np.asarray(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [1.0, 1.0],
            [0.0, 1.0],
        ],
        dtype=float,
    )
    connectivity = np.asarray([[0, 1, 2], [0, 2, 3]], dtype=int)
    planar_mesh = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.TRIANGLE, connectivity),),
    )
    solver_mesh = SolverMesh(
        planar_mesh=planar_mesh,
        top=np.asarray([10.0, 10.0], dtype=float),
        botm=np.asarray([[1.0, 1.0]], dtype=float),
        inactive_mask=np.zeros((1, 2), dtype=bool),
    )
    support = GmshSupportMetadata(
        cell_ids=np.asarray([0, 1], dtype=int),
        node_ids=np.asarray([0, 1, 2, 3], dtype=int),
        node_x_m=vertices[:, 0],
        node_y_m=vertices[:, 1],
        cell_node_indices=((0, 1, 2), (0, 2, 3)),
        cell_centroid_x_m=np.asarray([2.0 / 3.0, 1.0 / 3.0], dtype=float),
        cell_centroid_y_m=np.asarray([1.0 / 3.0, 2.0 / 3.0], dtype=float),
        edge_ids=np.asarray([0, 1, 2, 3, 4], dtype=int),
        edge_node_a_index=np.asarray([0, 1, 2, 3, 0], dtype=int),
        edge_node_b_index=np.asarray([1, 2, 3, 0, 2], dtype=int),
        edge_cell_a=np.asarray([0, 0, 1, 1, 0], dtype=int),
        edge_cell_b=np.asarray([-1, -1, -1, -1, 1], dtype=int),
        edge_midpoint_x_m=np.asarray([0.5, 1.0, 0.5, 0.0, 0.5], dtype=float),
        edge_midpoint_y_m=np.asarray([0.0, 0.5, 1.0, 0.5, 0.5], dtype=float),
        edge_kind=("boundary", "boundary", "boundary", "boundary", "internal"),
        edge_is_river=np.asarray(
            [False, False, False, False, bool(river_internal_edge)], dtype=bool
        ),
        geology_a_key=("", "", "", "", ""),
        geology_b_key=("", "", "", "", ""),
        boundary_labels_by_edge_id={}
        if boundary_labels_by_edge_id is None
        else dict(boundary_labels_by_edge_id),
    )
    return solver_mesh, support


def _build_unstructured_model(
    *,
    river_internal_edge: bool = False,
    boundary_labels_by_edge_id: dict[int, str] | None = None,
) -> Modflow6:
    model = _build_model()
    solver_mesh, support = _build_unstructured_runtime(
        river_internal_edge=river_internal_edge,
        boundary_labels_by_edge_id=boundary_labels_by_edge_id,
    )
    model.solver_mesh = solver_mesh
    model.runtime_mesh_support = support
    model.nlay = 1
    model.ncpl = 2
    model.dem_mask = np.zeros(2, dtype=bool)
    return model


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


def test_build_gmsh_support_metadata_from_bundle_like_payload() -> None:
    bundle = SimpleNamespace(
        bundle_dir=".",
        mesh_path="mesh_2d.msh",
        nodes=(
            SimpleNamespace(node_id=0, x=0.0, y=0.0),
            SimpleNamespace(node_id=1, x=1.0, y=0.0),
            SimpleNamespace(node_id=2, x=1.0, y=1.0),
            SimpleNamespace(node_id=3, x=0.0, y=1.0),
        ),
        cells=(
            SimpleNamespace(
                cell_id=0, node_indices=(0, 1, 2), centroid_x=2.0 / 3.0, centroid_y=1.0 / 3.0
            ),
            SimpleNamespace(
                cell_id=1, node_indices=(0, 2, 3), centroid_x=1.0 / 3.0, centroid_y=2.0 / 3.0
            ),
        ),
        edges=(
            SimpleNamespace(
                edge_id=0,
                node_a=0,
                node_b=1,
                cell_a=0,
                cell_b=None,
                edge_kind="boundary",
                is_river=False,
                geology_a_key="",
                geology_b_key="",
            ),
            SimpleNamespace(
                edge_id=1,
                node_a=1,
                node_b=2,
                cell_a=0,
                cell_b=None,
                edge_kind="boundary",
                is_river=False,
                geology_a_key="",
                geology_b_key="",
            ),
            SimpleNamespace(
                edge_id=2,
                node_a=2,
                node_b=3,
                cell_a=1,
                cell_b=None,
                edge_kind="boundary",
                is_river=False,
                geology_a_key="",
                geology_b_key="",
            ),
            SimpleNamespace(
                edge_id=3,
                node_a=3,
                node_b=0,
                cell_a=1,
                cell_b=None,
                edge_kind="boundary",
                is_river=False,
                geology_a_key="",
                geology_b_key="",
            ),
            SimpleNamespace(
                edge_id=4,
                node_a=0,
                node_b=2,
                cell_a=0,
                cell_b=1,
                edge_kind="internal",
                is_river=False,
                geology_a_key="",
                geology_b_key="",
            ),
        ),
    )

    support = build_gmsh_support_metadata(bundle)

    assert support is not None
    assert support.locate_cell_index_for_point(0.75, 0.25) == 0
    assert support.boundary_cell_indices_for_side("west_side").tolist() == [1]


def test_gmsh_support_metadata_collects_cells_from_internal_river_edge() -> None:
    _, support = _build_unstructured_runtime(river_internal_edge=True)

    assert support.river_cell_indices().tolist() == [0, 1]


def test_gmsh_support_metadata_resolves_cells_from_explicit_label() -> None:
    _, support = _build_unstructured_runtime(boundary_labels_by_edge_id={1: "east_custom"})

    assert support.cell_indices_for_label("east_custom").tolist() == [0]


def test_modflow6_builds_chd_from_scalar_and_transient_side_boundaries() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "west_side": SimpleNamespace(value=10.0),
            "east_side": SimpleNamespace(value=[20.0, 21.0]),
        },
        active_bc=["west_side", "east_side"],
    )

    chd_spd = model._build_side_boundary_chd_spd()

    # DISV format: [lay, cell_id, head]
    # west_side cells: row0*3+0=0, row1*3+0=3
    # east_side cells: row0*3+2=2, row1*3+2=5
    assert chd_spd[0][0] == [0, 0, pytest.approx(10.0)]
    assert chd_spd[0][-1] == [0, 5, pytest.approx(20.0)]
    assert chd_spd[1][-1] == [0, 5, pytest.approx(21.0)]


def test_modflow6_applies_first_boundary_value_to_start_heads() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "north_side": SimpleNamespace(value=[7.0, 8.0]),
        },
        active_bc=["north_side"],
    )
    # strt is now flat (nlay, ncpl)
    strt = np.zeros((1, 6), dtype=float)

    updated = model._apply_side_boundary_start_heads(strt)

    # North side cell_ids for 2x3 grid: 0, 1, 2
    assert np.all(updated[:, :3] == 7.0)
    assert np.all(updated[:, 3:] == 0.0)


def test_modflow6_resolves_boundary_forcing_without_runtime_binding() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "east_side": FlowBoundaryConditionConfig(
                id="east_side",
                type="dirichlet",
                units="cm",
                application_domain="east side",
                forcing={"mode": "constant", "value": 20.0},
            )
        },
        active_bc=["east_side"],
    )

    chd_spd = model._build_side_boundary_chd_spd()

    # DISV: [lay, cell_id, head] — east_side last cell_id=5
    assert chd_spd[0][-1] == [0, 5, pytest.approx(0.2)]
    assert chd_spd[1][-1] == [0, 5, pytest.approx(0.2)]


def test_modflow6_resolves_well_forcing_without_runtime_binding() -> None:
    model = _build_model()
    model.grid_ctx = SimpleNamespace(grid=None)
    model.flow = SimpleNamespace(
        sinks_sources={
            "wells": {
                "W1": FlowWellConfig(
                    cell=(0, 0, 0),
                    units="m3/day",
                    forcing={"mode": "constant", "value": -86400.0},
                )
            }
        },
        active_sinks_sources=["wells"],
    )

    wel_spd = model._build_well_stress_period_data(2)

    # DISV: [lay, cell_id, flux] — cell (0,0,0) → cell_id=0
    assert wel_spd[0] == [[0, 0, pytest.approx(-1.0)]]
    assert wel_spd[1] == [[0, 0, pytest.approx(-1.0)]]


def test_modflow6_resolves_absolute_xy_well_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model()
    model.grid_ctx = SimpleNamespace(grid=None)
    model.flow = SimpleNamespace(
        sinks_sources={
            "wells": {
                "W1": FlowWellConfig(
                    location_mode="absolute_xy",
                    x=0.75,
                    y=0.25,
                    flux=-1.0,
                )
            }
        },
        active_sinks_sources=["wells"],
    )

    wel_spd = model._build_well_stress_period_data(2)

    assert wel_spd[0] == [[0, 0, pytest.approx(-1.0)]]
    assert wel_spd[1] == [[0, 0, pytest.approx(-1.0)]]


def test_modflow6_builds_side_boundary_chd_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "west_side": SimpleNamespace(value=10.0),
            "east_side": SimpleNamespace(value=[20.0, 21.0]),
        },
        active_bc=["west_side", "east_side"],
    )

    chd_spd = model._build_side_boundary_chd_spd()

    period0 = sorted(chd_spd[0], key=lambda item: item[1])
    period1 = sorted(chd_spd[1], key=lambda item: item[1])
    assert period0 == [[0, 0, pytest.approx(20.0)], [0, 1, pytest.approx(10.0)]]
    assert period1 == [[0, 0, pytest.approx(21.0)], [0, 1, pytest.approx(10.0)]]


def test_modflow6_applies_side_boundary_start_heads_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "west_side": SimpleNamespace(value=[7.0, 8.0]),
        },
        active_bc=["west_side"],
    )
    strt = np.zeros((1, 2), dtype=float)

    updated = model._apply_side_boundary_start_heads(strt)

    assert updated[0, 0] == pytest.approx(0.0)
    assert updated[0, 1] == pytest.approx(7.0)


def test_modflow6_builds_stream_boundary_chd_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model(river_internal_edge=True)
    model.flow = SimpleNamespace(
        boundary_conditions={
            "stream": SimpleNamespace(value=7.0),
        },
        active_bc=["stream"],
    )

    chd_spd, stream_mask = model._build_stream_boundary_chd_spd()

    assert stream_mask.tolist() == [True, True]
    assert chd_spd[0] == [[0, 0, pytest.approx(7.0)], [0, 1, pytest.approx(7.0)]]
    assert chd_spd[1] == [[0, 0, pytest.approx(7.0)], [0, 1, pytest.approx(7.0)]]


def test_modflow6_applies_stream_start_heads_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model(river_internal_edge=True)
    model.flow = SimpleNamespace(
        initial_conditions=FlowInitialConditions(
            h=FlowInitialCondition(id="h", type="custom", value=2.0)
        ),
        boundary_conditions={
            "stream": SimpleNamespace(value=7.0),
        },
        active_bc=["stream"],
    )

    strt = model._build_start_heads(model.solver_mesh)

    assert np.allclose(strt[0], [7.0, 7.0])


def test_modflow6_uses_support_label_for_side_boundary_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model(boundary_labels_by_edge_id={1: "east_custom"})
    model.flow = SimpleNamespace(
        boundary_conditions={
            "west_side": SimpleNamespace(value=10.0),
            "east_side": FlowBoundaryConditionConfig(
                id="east_side",
                value=6.0,
                units="m",
                type="dirichlet",
                application_domain="east side",
                support_label="east_custom",
            ),
        },
        active_bc=["east_side"],
    )

    chd_spd = model._build_side_boundary_chd_spd()

    assert chd_spd[0] == [[0, 0, pytest.approx(6.0)]]
    assert chd_spd[1] == [[0, 0, pytest.approx(6.0)]]


def test_modflow6_uses_support_label_for_stream_boundary_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model(boundary_labels_by_edge_id={0: "ditch_custom"})
    model.flow = SimpleNamespace(
        boundary_conditions={
            "stream": FlowBoundaryConditionConfig(
                id="stream",
                value=5.0,
                units="m",
                type="dirichlet",
                application_domain="top",
                support_label="ditch_custom",
            ),
        },
        active_bc=["stream"],
    )

    chd_spd, stream_mask = model._build_stream_boundary_chd_spd()

    assert stream_mask.tolist() == [True, False]
    assert chd_spd[0] == [[0, 0, pytest.approx(5.0)]]
    assert chd_spd[1] == [[0, 0, pytest.approx(5.0)]]


def test_modflow6_builds_start_heads_from_typed_initial_conditions() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        initial_conditions=FlowInitialConditions(h=FlowInitialCondition(id="h", type="top")),
        boundary_conditions={},
        active_bc=[],
    )
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    botm_2d = np.array([[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]], dtype=float)
    solver_mesh = SolverMesh.from_structured_arrays(
        nrow=2,
        ncol=3,
        top=top,
        botm=np.stack([botm_2d]),
    )

    strt = model._build_start_heads(solver_mesh)

    # DISV: strt shape is (nlay, ncpl)
    assert strt.shape == (1, 6)
    assert np.allclose(strt[0], top.ravel())


def test_modflow6_accepts_bottom_initial_condition_name() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        initial_conditions=FlowInitialConditions(h=FlowInitialCondition(id="h", type="bottom")),
        boundary_conditions={},
        active_bc=[],
    )
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    botm_layer1 = np.array([[6.0, 6.0, 6.0], [6.0, 6.0, 6.0]], dtype=float)
    botm_layer2 = np.array([[2.0, 3.0, 4.0], [5.0, 6.0, 7.0]], dtype=float)
    solver_mesh = SolverMesh.from_structured_arrays(
        nrow=2,
        ncol=3,
        top=top,
        botm=np.stack([botm_layer1, botm_layer2]),
    )

    strt = model._build_start_heads(solver_mesh)

    # DISV: strt shape is (nlay, ncpl) — all layers start at deepest botm
    assert np.allclose(strt[0], botm_layer2.ravel())


def test_modflow6_binds_recharge_from_flow_sinks_sources() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        sinks_sources={
            "recharge": FlowRechargeConfig(
                values=pd.Series([0.5, 0.3], dtype=float),
                first_clim="first",
                units="mm/day",
            )
        },
        active_sinks_sources=["recharge"],
    )

    model._bind_recharge_from_flow()
    spd = model._recharge_to_spd()

    # DISV: recharge arrays are flat (ncpl,)
    assert spd[0].shape == (6,)
    assert np.allclose(spd[0], 0.5e-3 / 86400.0)
    assert np.allclose(spd[1], 0.3e-3 / 86400.0)


def test_modflow6_routes_negative_recharge_to_evt_payload() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        sinks_sources={
            "recharge": FlowRechargeConfig(
                values=pd.Series([0.5, -0.3], dtype=float),
                first_clim="first",
                units="mm/day",
                negative_to_evt=True,
            )
        },
        active_sinks_sources=["recharge"],
    )

    model._bind_recharge_from_flow()
    spd = model._recharge_to_spd()

    assert np.allclose(spd[0], 0.5e-3 / 86400.0)
    assert np.allclose(spd[1], 0.0)
    assert model._evt_rate_payload is not None
    assert model._evt_rate_payload[0] == pytest.approx(0.0)
    assert model._evt_rate_payload[1] == pytest.approx(0.3e-3 / 86400.0)


def test_modflow6_resolves_point_recharge_and_routes_negative_periods_to_evt() -> None:
    model = _build_model()
    top = np.full((2, 3), 10.0, dtype=float)
    botm = np.zeros((1, 2, 3), dtype=float)
    model.solver_mesh = SolverMesh.from_structured_arrays(
        nrow=2,
        ncol=3,
        top=top,
        botm=botm,
    )
    point = _make_recharge_point_record(
        station_id="R1",
        x=0.5,
        y=0.5,
        january_value_mm_day=8.0,
        february_value_mm_day=-4.0,
    )
    model.flow = SimpleNamespace(
        sinks_sources={
            "recharge": FlowRechargeConfig(
                values=0.0,
                heterogeneous_source=LoadResult(points=[point]),
                interpolation_method="nearest",
                negative_to_evt=True,
            )
        },
        active_sinks_sources=["recharge"],
    )

    model._bind_recharge_from_flow()
    mf6_flow_adapter.resolve_deferred_heterogeneous_recharge(model)

    january_expected = 8.0e-3 / 86400.0
    february_evt_expected = 4.0e-3 / 86400.0
    np.testing.assert_allclose(
        model.recharge[0],
        np.full((2, 3), january_expected, dtype=float),
    )
    np.testing.assert_allclose(model.recharge[1], np.zeros((2, 3), dtype=float))
    assert model._evt_rate_payload is not None
    np.testing.assert_allclose(
        model._evt_rate_payload[0],
        np.zeros((2, 3), dtype=float),
    )
    np.testing.assert_allclose(
        model._evt_rate_payload[1],
        np.full((2, 3), february_evt_expected, dtype=float),
    )


def test_modflow6_resolves_point_recharge_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model()
    point = _make_recharge_point_record(
        station_id="R1",
        x=0.75,
        y=0.25,
        january_value_mm_day=8.0,
    )
    model.flow = SimpleNamespace(
        sinks_sources={
            "recharge": FlowRechargeConfig(
                values=0.0,
                heterogeneous_source=LoadResult(points=[point]),
                interpolation_method="nearest",
            )
        },
        active_sinks_sources=["recharge"],
    )

    model._bind_recharge_from_flow()
    mf6_flow_adapter.resolve_deferred_heterogeneous_recharge(model)

    expected = 8.0e-3 / 86400.0
    np.testing.assert_allclose(
        model.recharge[0],
        np.full(2, expected, dtype=float),
    )
    np.testing.assert_allclose(
        model.recharge[1],
        np.full(2, expected, dtype=float),
    )


def test_modflow6_extracts_evt_payload_from_negative_2d_recharge() -> None:
    model = _build_model()

    clipped_rch, evt_data = model._extract_evt_payload_2d(
        {
            0: np.array([1.0e-6, -2.0e-6], dtype=float),
            1: np.array([-3.0e-6, 4.0e-6], dtype=float),
        },
        True,
    )

    assert evt_data is not None
    np.testing.assert_allclose(clipped_rch[0], np.array([1.0e-6, 0.0], dtype=float))
    np.testing.assert_allclose(clipped_rch[1], np.array([0.0, 4.0e-6], dtype=float))
    np.testing.assert_allclose(evt_data[0], np.zeros(2, dtype=float))
    np.testing.assert_allclose(evt_data[1], np.array([3.0e-6, 0.0], dtype=float))


def test_modflow6_builds_evt_stress_period_data_from_routed_payload() -> None:
    model = _build_model()
    model.flow_regime = "transient"
    model._evt_rate_payload = {0: 0.0, 1: 1.0e-6}
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    botm_2d = np.array([[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]], dtype=float)
    solver_mesh = SolverMesh.from_structured_arrays(
        nrow=2,
        ncol=3,
        top=top,
        botm=np.stack([botm_2d]),
    )

    evt_spd = model._build_evt_stress_period_data(
        solver_mesh,
        ocean_support_mask=np.zeros(6, dtype=bool),
        stream_support_mask=np.zeros(6, dtype=bool),
    )

    assert evt_spd is not None
    assert evt_spd[0] == []
    assert len(evt_spd[1]) == 6
    assert evt_spd[1][0] == [0, 0, pytest.approx(10.0), pytest.approx(1.0e-6), pytest.approx(1.0)]


def test_modflow6_keeps_rewet_disabled_by_default() -> None:
    model = _build_model()
    model.flow_regime = "transient"
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    botm_2d = np.array([[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]], dtype=float)
    solver_mesh = SolverMesh.from_structured_arrays(
        nrow=2,
        ncol=3,
        top=top,
        botm=np.stack([botm_2d]),
    )

    rewet_record, wetdry = model._resolve_rewet_npf_options(solver_mesh)

    assert rewet_record is None
    assert wetdry is None


def test_modflow6_enables_rewet_when_requested() -> None:
    model = _build_model()
    model.flow_regime = "transient"
    model.modflow_config = model.modflow_config.model_copy(
        update={
            "runtime": model.modflow_config.runtime.model_copy(update={"mf6_enable_rewet": True})
        }
    )
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    botm_2d = np.array([[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]], dtype=float)
    solver_mesh = SolverMesh.from_structured_arrays(
        nrow=2,
        ncol=3,
        top=top,
        botm=np.stack([botm_2d]),
    )

    rewet_record, wetdry = model._resolve_rewet_npf_options(solver_mesh)

    assert rewet_record == [
        "WETFCT",
        pytest.approx(0.1),
        "IWETIT",
        1,
        "IHDWET",
        0,
    ]
    np.testing.assert_allclose(wetdry, np.full((1, 6), 0.1, dtype=float))


def test_modflow6_defaults_to_zero_recharge_when_inactive() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        sinks_sources={},
        active_sinks_sources=[],
    )

    model._bind_recharge_from_flow()
    spd = model._recharge_to_spd()

    assert spd[0].shape == (6,)
    assert np.allclose(spd[0], 0.0)
    assert np.allclose(spd[1], 0.0)


def test_modflow6_flow_adapter_builds_wells_from_forcing_payload() -> None:
    model = _build_model()
    model.grid_ctx = SimpleNamespace(grid=None)
    model.flow = SimpleNamespace(
        sinks_sources={
            "wells": {
                "W1": FlowWellConfig(
                    cell=(0, 0, 0),
                    units="m3/day",
                    forcing={"mode": "constant", "value": -86400.0},
                )
            }
        },
        active_sinks_sources=["wells"],
    )

    wel_spd = mf6_flow_adapter.build_well_stress_period_data(model, 2)

    assert wel_spd[0] == [[0, 0, pytest.approx(-1.0)]]
    assert wel_spd[1] == [[0, 0, pytest.approx(-1.0)]]


def test_modflow6_flow_adapter_extracts_evt_payload_from_negative_2d_recharge() -> None:
    clipped, evt = mf6_flow_adapter.extract_evt_payload_2d(
        {
            0: np.asarray([1.0, -2.0], dtype=float),
            1: np.asarray([-3.0, 4.0], dtype=float),
        },
        True,
    )

    assert evt is not None
    np.testing.assert_allclose(clipped[0], np.asarray([1.0, 0.0], dtype=float))
    np.testing.assert_allclose(clipped[1], np.asarray([0.0, 4.0], dtype=float))
    np.testing.assert_allclose(evt[0], np.asarray([0.0, 0.0], dtype=float))
    np.testing.assert_allclose(evt[1], np.asarray([3.0, 0.0], dtype=float))
