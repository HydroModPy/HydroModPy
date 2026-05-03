from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

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
from hydromodpy.solver.modflow6.builders import (
    apply_side_boundary_start_heads,
    bind_recharge_from_flow,
    build_evt_stress_period_data,
    build_side_boundary_chd_spd,
    build_start_heads,
    build_stream_boundary_chd_spd,
    build_well_stress_period_data,
    extract_evt_payload_2d,
    recharge_to_spd,
    resolve_deferred_heterogeneous_recharge,
    resolve_rewet_npf_options,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.spatial.mesh.gmsh_grid import (
    GmshSupportMetadata,
    build_gmsh_support_metadata,
)


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
                cell_id=0,
                node_indices=(0, 1, 2),
                centroid_x=2.0 / 3.0,
                centroid_y=1.0 / 3.0,
                z_top_mean=30.0,
                z_bottom_mean=10.0,
            ),
            SimpleNamespace(
                cell_id=1,
                node_indices=(0, 2, 3),
                centroid_x=1.0 / 3.0,
                centroid_y=2.0 / 3.0,
                z_top_mean=40.0,
                z_bottom_mean=20.0,
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
    np.testing.assert_allclose(support.cell_z_top_m, np.asarray([30.0, 40.0], dtype=float))
    np.testing.assert_allclose(support.cell_z_bottom_m, np.asarray([10.0, 20.0], dtype=float))


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

    chd_spd = build_side_boundary_chd_spd(model)

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

    updated = apply_side_boundary_start_heads(model, strt)

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

    chd_spd = build_side_boundary_chd_spd(model)

    # DISV: [lay, cell_id, head] - east_side last cell_id=5
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

    wel_spd = build_well_stress_period_data(model, 2)

    # DISV: [lay, cell_id, flux] - cell (0,0,0) → cell_id=0
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

    wel_spd = build_well_stress_period_data(model, 2)

    assert wel_spd[0] == [[0, 0, pytest.approx(-1.0)]]
    assert wel_spd[1] == [[0, 0, pytest.approx(-1.0)]]


def test_modflow6_coordinate_well_ignores_inherited_cell_payload() -> None:
    model = _build_unstructured_model()
    model.grid_ctx = SimpleNamespace(grid=None)
    model.flow = SimpleNamespace(
        sinks_sources={
            "wells": {
                "W1": {
                    "cell": (0, 0, 1),
                    "location_mode": "absolute_xy",
                    "layer": 0,
                    "x": 0.75,
                    "y": 0.25,
                    "flux": -1.0,
                }
            }
        },
        active_sinks_sources=["wells"],
    )

    wel_spd = build_well_stress_period_data(model, 1)

    assert wel_spd[0] == [[0, 0, pytest.approx(-1.0)]]


def test_modflow6_rejects_unstructured_well_outside_runtime_mesh() -> None:
    model = _build_unstructured_model()
    model.grid_ctx = SimpleNamespace(grid=None)
    model.flow = SimpleNamespace(
        sinks_sources={
            "wells": {
                "W1": FlowWellConfig(
                    location_mode="absolute_xy",
                    x=2.0,
                    y=2.0,
                    flux=-1.0,
                )
            }
        },
        active_sinks_sources=["wells"],
    )

    with pytest.raises(ValueError, match="outside the .* mesh domain"):
        build_well_stress_period_data(model, 2)


def test_modflow6_rejects_well_flux_length_mismatch() -> None:
    model = _build_model()
    model.grid_ctx = SimpleNamespace(grid=None)
    model.flow = SimpleNamespace(
        sinks_sources={
            "wells": {
                "W1": FlowWellConfig(
                    cell=(0, 0, 0),
                    flux=[-1.0, -2.0, -3.0],
                )
            }
        },
        active_sinks_sources=["wells"],
    )

    with pytest.raises(ValueError, match="must be 1 or match nper"):
        build_well_stress_period_data(model, 2)


def test_modflow6_builds_side_boundary_chd_on_unstructured_runtime_mesh() -> None:
    model = _build_unstructured_model()
    model.flow = SimpleNamespace(
        boundary_conditions={
            "west_side": SimpleNamespace(value=10.0),
            "east_side": SimpleNamespace(value=[20.0, 21.0]),
        },
        active_bc=["west_side", "east_side"],
    )

    chd_spd = build_side_boundary_chd_spd(model)

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

    updated = apply_side_boundary_start_heads(model, strt)

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

    chd_spd, stream_mask = build_stream_boundary_chd_spd(model)

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

    strt = build_start_heads(model, model.solver_mesh)

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

    chd_spd = build_side_boundary_chd_spd(model)

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

    chd_spd, stream_mask = build_stream_boundary_chd_spd(model)

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

    strt = build_start_heads(model, solver_mesh)

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

    strt = build_start_heads(model, solver_mesh)

    # DISV: strt shape is (nlay, ncpl) - all layers start at deepest botm
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

    bind_recharge_from_flow(model)
    spd = recharge_to_spd(model)

    # DISV: recharge arrays are flat (ncpl,)
    assert spd[0].shape == (6,)
    assert np.allclose(spd[0], 0.5e-3 / 86400.0)
    assert np.allclose(spd[1], 0.3e-3 / 86400.0)


def test_modflow6_rejects_nonfinite_direct_recharge() -> None:
    model = _build_model()
    model.recharge = np.asarray([1.0e-8, np.nan], dtype=float)

    with pytest.raises(ValueError, match="model.recharge"):
        bind_recharge_from_flow(model)


def test_modflow6_rejects_bad_recharge_flat_shape() -> None:
    model = _build_model()
    model.recharge = np.asarray([1.0e-8, 2.0e-8, 3.0e-8], dtype=float)

    with pytest.raises(ValueError, match="sequence length"):
        recharge_to_spd(model)


def test_modflow6_rejects_missing_recharge_mapping_period() -> None:
    model = _build_model()
    model.recharge = {0: np.full(6, 1.0e-8, dtype=float)}

    with pytest.raises(ValueError, match="missing stress period 1"):
        recharge_to_spd(model)


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


def test_modflow6_extracts_evt_payload_from_negative_2d_recharge() -> None:
    model = _build_model()

    clipped_rch, evt_data = extract_evt_payload_2d(
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

    evt_spd = build_evt_stress_period_data(
        model,
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

    rewet_record, wetdry = resolve_rewet_npf_options(model, solver_mesh)

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

    rewet_record, wetdry = resolve_rewet_npf_options(model, solver_mesh)

    assert rewet_record == [
        "WETFCT",
        pytest.approx(0.1),
        "IWETIT",
        1,
        "IHDWET",
        0,
    ]
    np.testing.assert_allclose(wetdry, np.full((1, 6), 0.1, dtype=float))


def test_modflow6_disables_xt3d_by_default() -> None:
    model = _build_model()

    assert model._xt3d_requested_value() is None
    assert model._xt3d_is_enabled() is False
    assert model._resolve_xt3d_npf_options() is None


def test_modflow6_enables_xt3d_when_requested() -> None:
    model = _build_model()
    model.modflow_config = model.modflow_config.model_copy(
        update={
            "runtime": model.modflow_config.runtime.model_copy(update={"mf6_enable_xt3d": True})
        }
    )

    assert model._xt3d_is_enabled() is True
    assert model._resolve_xt3d_npf_options() == ["XT3D"]


def test_modflow6_auto_enables_xt3d_on_unstructured_mesh() -> None:
    model = _build_unstructured_model()

    assert model._xt3d_requested_value() is None
    assert model._xt3d_activation_mode(model.solver_mesh) == "auto_unstructured"
    assert model._xt3d_is_enabled(model.solver_mesh) is True
    assert model._resolve_xt3d_npf_options(model.solver_mesh) == ["XT3D"]


def test_modflow6_explicit_false_disables_xt3d_on_unstructured_mesh() -> None:
    model = _build_unstructured_model()
    model.modflow_config = model.modflow_config.model_copy(
        update={
            "runtime": model.modflow_config.runtime.model_copy(update={"mf6_enable_xt3d": False})
        }
    )

    assert model._xt3d_requested_value() is False
    assert model._xt3d_activation_mode(model.solver_mesh) == "explicit_false"
    assert model._xt3d_is_enabled(model.solver_mesh) is False
    assert model._resolve_xt3d_npf_options(model.solver_mesh) is None


def test_modflow6_forces_complex_ims_when_xt3d_is_active() -> None:
    model = _build_unstructured_model()
    model.modflow_config = model.modflow_config.model_copy(
        update={
            "runtime": model.modflow_config.runtime.model_copy(
                update={"mf6_ims_complexity": "SIMPLE"}
            )
        }
    )

    assert model._xt3d_is_enabled(model.solver_mesh) is True
    assert model._resolve_ims_complexity(model.solver_mesh) == "COMPLEX"


def test_modflow6_defaults_to_zero_recharge_when_inactive() -> None:
    model = _build_model()
    model.flow = SimpleNamespace(
        sinks_sources={},
        active_sinks_sources=[],
    )

    bind_recharge_from_flow(model)
    spd = recharge_to_spd(model)

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

    wel_spd = build_well_stress_period_data(model, 2)

    assert wel_spd[0] == [[0, 0, pytest.approx(-1.0)]]
    assert wel_spd[1] == [[0, 0, pytest.approx(-1.0)]]


def test_modflow6_flow_adapter_extracts_evt_payload_from_negative_2d_recharge() -> None:
    clipped, evt = extract_evt_payload_2d(
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
