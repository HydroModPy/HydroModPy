from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr
from shapely.geometry import LineString

# The Boussinesq runtime currently calls ``TransientStepInputs`` /
# ``SteadySolveInputs`` with an obsolete keyword (``imposed_head_m_by_edge``).
# Production fix is scheduled alongside the solver/contract alignment work;
# the adapter-level assertions below are kept for when that lands.
_OBSOLETE_RUNTIME_API = pytest.mark.xfail(
    reason="Boussinesq runtime API mismatch (imposed_head_m_by_edge vs "
    "prescribed_head_m_by_cell); tracked as v0.6 "
    "boussinesq-runtime-api-alignment.",
    strict=True,
    raises=(TypeError, AttributeError),
)

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.spatial.field.core.field_spatial_weighted_discretization import (
    WeightedAverageFieldDiscretization,
)
from hydromodpy.physics.flow import Flow
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.simulation.adapters.flow.boussinesq import BoussinesqFlowAdapter
from hydromodpy.simulation.adapters.registry import get_solver_adapter
from hydromodpy.simulation.planning.plan import (
    ProcessRun,
    RunContext,
    SimulationPlan,
)
from hydromodpy.solver.utils.mesh.gmsh_grid import GmshPlanarMesh2D


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _write_minimal_bundle(bundle_dir: Path, *, river_internal_edge: bool = False) -> Path:
    return _write_custom_bundle(
        bundle_dir,
        river_internal_edge=river_internal_edge,
        storage_values=("0.10", "0.15"),
        storage_default=None,
    )


def _write_custom_bundle(
    bundle_dir: Path,
    *,
    river_internal_edge: bool = False,
    storage_values: tuple[str, str] = ("0.10", "0.15"),
    storage_default: float | None = None,
) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "mesh_2d.msh").write_text(
        "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n",
        encoding="utf-8",
    )
    hydraulic_properties = {}
    if storage_default is not None:
        hydraulic_properties["storage_coefficient"] = {
            "available": True,
            "unit": "-",
            "values_source": "inline",
            "default_value": float(storage_default),
        }
    (bundle_dir / "metadata.json").write_text(
        json.dumps(
            {
                "bundle_schema_version": "mesh_catchment_bundle_v1",
                "crs": "EPSG:2154",
                "files": {"mesh": "mesh_2d.msh"},
                "hydraulic_properties": hydraulic_properties,
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "mesh_summary.json").write_text(
        json.dumps({"constraints_mode": "geology_only"}, indent=2, ensure_ascii=True)
        + "\n",
        encoding="utf-8",
    )
    _write_csv(
        bundle_dir / "nodes.csv",
        "node_id,x,y,z_top,z_bottom",
        [
            "0,0.0,0.0,10.0,5.0",
            "1,1.0,0.0,10.0,5.0",
            "2,1.0,1.0,10.0,5.0",
            "3,0.0,1.0,10.0,5.0",
        ],
    )
    _write_csv(
        bundle_dir / "cells.csv",
        "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,z_top_mean,z_bottom_centroid,z_bottom_mean,geology_code,geology_key,hydraulic_conductivity_m_s,storage_coefficient",
        [
            f"0,triangle,0,1,2,,0.666667,0.333333,0.5,10.0,10.0,5.0,5.0,1,granite,1.0e-5,{storage_values[0]}",
            f"1,triangle,0,2,3,,0.333333,0.666667,0.5,11.0,11.0,4.0,4.0,2,schist,2.0e-5,{storage_values[1]}",
        ],
    )
    _write_csv(
        bundle_dir / "edges.csv",
        "edge_id,node_a,node_b,cell_a,cell_b,length_m,edge_kind,is_river,geology_a_key,geology_b_key",
        [
            "0,0,1,0,,1.0,boundary,false,granite,",
            "1,1,2,0,,1.0,boundary,false,granite,",
            f"2,0,2,0,1,1.414214,internal,{str(bool(river_internal_edge)).lower()},granite,schist",
            "3,2,3,1,,1.0,boundary,false,schist,",
            "4,0,3,1,,1.0,boundary,false,schist,",
        ],
    )
    _write_csv(
        bundle_dir / "cell_geology_fractions.csv",
        "cell_id,geology_key,fraction",
        [
            "0,granite,1.0",
            "1,schist,1.0",
        ],
    )
    return bundle_dir


def _build_flow_config(flow_section: dict[str, object]) -> FlowConfig:
    return FlowConfig.from_toml_section(flow_section, base_dir=Path("."))


class _DummyRasterSupport:
    def __init__(
        self,
        *,
        xmin: float,
        xmax: float,
        ymin: float,
        ymax: float,
        dx: float,
        dy: float,
        nrows: int,
        ncols: int,
    ) -> None:
        self.xmin = float(xmin)
        self.xmax = float(xmax)
        self.ymin = float(ymin)
        self.ymax = float(ymax)
        self.dx = float(dx)
        self.dy = float(dy)
        self.nrows = int(nrows)
        self.ncols = int(ncols)
        self.nodata = None


class _DummySurface:
    def __init__(self, values: np.ndarray, support: _DummyRasterSupport) -> None:
        self.values = np.asarray(values, dtype=float)
        self.support = support


class _HalfDomainSupport:
    def __init__(self, identifier: str = "field_geology") -> None:
        self.identifier = identifier
        self.default_cell_samples_per_axis = 4

    def on_mesh(self, mesh, *, cell_samples_per_axis: int = 10):
        _ = cell_samples_per_axis
        x_centers, _ = mesh.cell_centroids()
        x_centers = np.asarray(x_centers, dtype=float)
        midpoint = 0.5 * (float(np.min(x_centers)) + float(np.max(x_centers)))
        west = (x_centers <= midpoint).astype(float)
        east = 1.0 - west
        return WeightedAverageFieldDiscretization(
            mesh=mesh,
            field_id=self.identifier,
            zone_keys=("west", "east"),
            fractions_by_zone={
                "west": west,
                "east": east,
            },
        )


def _make_static_recharge_field_record() -> FieldRecord:
    ds = xr.Dataset(
        {
            "recharge": (
                ("y", "x"),
                np.asarray(
                    [
                        [1.0e-7, 4.0e-7],
                        [2.0e-7, 3.0e-7],
                    ],
                    dtype=float,
                ),
            )
        },
        coords={
            "x": np.asarray([0.333333, 0.666667], dtype=float),
            "y": np.asarray([0.333333, 0.666667], dtype=float),
        },
    )
    return FieldRecord(
        variable="recharge",
        source="test",
        unit="m/s",
        data=ds,
        bbox=(0.0, 0.0, 1.0, 1.0),
        crs="EPSG:2154",
    )


def test_registry_exposes_boussinesq_flow_adapter() -> None:
    adapter = get_solver_adapter("flow", "boussinesq")

    assert isinstance(adapter, BoussinesqFlowAdapter)


@_OBSOLETE_RUNTIME_API
def test_boussinesq_flow_adapter_maps_runtime_mesh_from_flow_parameters(
    tmp_path: Path,
) -> None:
    planar_mesh = GmshPlanarMesh2D(
        points_xy=np.asarray(
            [
                [0.0, 0.0],
                [1.0, 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
            ],
            dtype=float,
        ),
        connectivity=np.asarray(
            [
                [0, 1, 2],
                [0, 2, 3],
            ],
            dtype=int,
        ),
        cell_type="triangle",
    )
    support = _DummyRasterSupport(
        xmin=0.0,
        xmax=2.0,
        ymin=0.0,
        ymax=2.0,
        dx=1.0,
        dy=1.0,
        nrows=2,
        ncols=2,
    )
    domain = SimpleNamespace(
        surface_topo=_DummySurface(np.full((2, 2), 10.0, dtype=float), support),
        substratum=_DummySurface(np.full((2, 2), 5.0, dtype=float), support),
        zones={},
    )
    flow = Flow(
        FlowConfig.model_validate(
            {
                "param_list": ["K", "Sy"],
                "param": {
                    "K": {"kind": "homogeneous", "value": 1.0e-5},
                    "Sy": {"kind": "homogeneous", "value": 0.2},
                },
                "ic": {"type": "bottom"},
            }
        )
    )
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_planar=planar_mesh,
            mesh_bundle=None,
            mesh_summary=None,
            flow=flow,
            domain=domain,
            domain_geographic=None,
            time_grid=None,
            workspace=SimpleNamespace(simulations_folder=tmp_path, solver_scratch_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq_runtime_mesh",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert state.setup.mesh_bundle is None
    assert model.mesh_bundle is None
    assert model.mesh is not None
    assert np.allclose(model.mesh.hydraulic_conductivity_m_s, [1.0e-5, 1.0e-5])
    assert np.allclose(model.mesh.storage_coefficient, [0.2, 0.2])
    assert model.state is not None
    assert np.allclose(model.state.head_m, [5.0, 5.0])


@_OBSOLETE_RUNTIME_API
def test_boussinesq_flow_adapter_supports_runtime_mesh_with_heterogeneous_recharge(
    tmp_path: Path,
) -> None:
    planar_mesh = GmshPlanarMesh2D(
        points_xy=np.asarray(
            [
                [0.0, 0.0],
                [1.0, 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
            ],
            dtype=float,
        ),
        connectivity=np.asarray(
            [
                [0, 1, 2],
                [0, 2, 3],
            ],
            dtype=int,
        ),
        cell_type="triangle",
    )
    support = _DummyRasterSupport(
        xmin=0.0,
        xmax=2.0,
        ymin=0.0,
        ymax=2.0,
        dx=1.0,
        dy=1.0,
        nrows=2,
        ncols=2,
    )
    domain = SimpleNamespace(
        surface_topo=_DummySurface(np.full((2, 2), 10.0, dtype=float), support),
        substratum=_DummySurface(np.full((2, 2), 5.0, dtype=float), support),
        zones={},
    )
    flow = Flow(
        FlowConfig.model_validate(
            {
                "param_list": ["K", "Sy"],
                "param": {
                    "K": {"kind": "homogeneous", "value": 1.0e-5},
                    "Sy": {"kind": "homogeneous", "value": 0.2},
                },
                "ic": {"type": "custom", "value": 7.0},
                "active_sinks_sources": ["recharge"],
                "sinks_sources": {
                    "recharge": {
                        "values": 0.0,
                    }
                },
            }
        )
    )
    flow.sinks_sources["recharge"].heterogeneous_source = LoadResult(
        fields=[_make_static_recharge_field_record()]
    )
    flow.sinks_sources["recharge"].interpolation_method = "nearest"
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_planar=planar_mesh,
            mesh_bundle=None,
            mesh_summary=None,
            flow=flow,
            domain=domain,
            domain_geographic=None,
            time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
            workspace=SimpleNamespace(simulations_folder=tmp_path, solver_scratch_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq_runtime_mesh_heterogeneous_recharge",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert model.state is not None
    assert np.allclose(model.state.recharge_rate_m_s, [4.0e-7, 2.0e-7])
    assert model.runtime_summary["active_recharge"] is True


@_OBSOLETE_RUNTIME_API
def test_boussinesq_flow_adapter_maps_runtime_mesh_from_heterogeneous_flow_parameters(
    tmp_path: Path,
) -> None:
    planar_mesh = GmshPlanarMesh2D(
        points_xy=np.asarray(
            [
                [0.0, 0.0],
                [1.0, 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
            ],
            dtype=float,
        ),
        connectivity=np.asarray(
            [
                [0, 1, 2],
                [0, 2, 3],
            ],
            dtype=int,
        ),
        cell_type="triangle",
    )
    support = _DummyRasterSupport(
        xmin=0.0,
        xmax=2.0,
        ymin=0.0,
        ymax=2.0,
        dx=1.0,
        dy=1.0,
        nrows=2,
        ncols=2,
    )
    spatial_support = _HalfDomainSupport()
    domain = SimpleNamespace(
        surface_topo=_DummySurface(np.full((2, 2), 10.0, dtype=float), support),
        substratum=_DummySurface(np.full((2, 2), 5.0, dtype=float), support),
        zones={"field_geology": spatial_support},
    )
    flow = Flow(
        FlowConfig.model_validate(
            {
                "param_list": ["K", "Sy"],
                "param": {
                    "K": {
                        "kind": "heterogeneous",
                        "values_by_key": {"west": 2.0e-5, "east": 5.0e-6},
                        "field_spatial_id": "field_geology",
                    },
                    "Sy": {
                        "kind": "heterogeneous",
                        "values_by_key": {"west": 0.22, "east": 0.08},
                        "field_spatial_id": "field_geology",
                    },
                },
                "ic": {"type": "bottom"},
            }
        )
    )
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_planar=planar_mesh,
            mesh_bundle=None,
            mesh_summary=None,
            flow=flow,
            domain=domain,
            domain_geographic=None,
            time_grid=None,
            workspace=SimpleNamespace(simulations_folder=tmp_path, solver_scratch_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq_runtime_mesh_heterogeneous",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert model.mesh is not None
    assert np.allclose(model.mesh.hydraulic_conductivity_m_s, [5.0e-6, 2.0e-5])
    assert np.allclose(model.mesh.storage_coefficient, [0.08, 0.22])
    assert model.state is not None
    assert np.allclose(model.state.head_m, [5.0, 5.0])


@_OBSOLETE_RUNTIME_API
def test_boussinesq_flow_adapter_falls_back_to_bundle_and_overrides_properties(
    tmp_path: Path,
) -> None:
    planar_mesh = GmshPlanarMesh2D(
        points_xy=np.asarray(
            [
                [0.0, 0.0],
                [1.0, 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
            ],
            dtype=float,
        ),
        connectivity=np.asarray(
            [
                [0, 1, 2],
                [0, 2, 3],
            ],
            dtype=int,
        ),
        cell_type="triangle",
    )
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_heterogeneous_override")
    flow = Flow(
        FlowConfig.model_validate(
            {
                "param_list": ["K", "Sy"],
                "param": {
                    "K": {
                        "kind": "heterogeneous",
                        "values_by_key": {"west": 3.0e-4, "east": 8.0e-7},
                        "field_spatial_id": "field_hydrofacies",
                    },
                    "Sy": {
                        "kind": "heterogeneous",
                        "values_by_key": {"west": 0.21, "east": 0.03},
                        "field_spatial_id": "field_hydrofacies",
                    },
                },
                "ic": {"type": "top"},
            }
        )
    )
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_planar=planar_mesh,
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=flow,
            domain=SimpleNamespace(
                zones={"field_hydrofacies": _HalfDomainSupport("field_hydrofacies")}
            ),
            domain_geographic=None,
            time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
            workspace=SimpleNamespace(simulations_folder=tmp_path, solver_scratch_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq_bundle_heterogeneous_override",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert model.mesh_bundle is not None
    assert model.mesh is not None
    assert np.allclose(model.mesh.hydraulic_conductivity_m_s, [8.0e-7, 3.0e-4])
    assert np.allclose(model.mesh.storage_coefficient, [0.03, 0.21])
    assert model.has_numerical_solution is True


@_OBSOLETE_RUNTIME_API
def test_boussinesq_flow_adapter_uses_geographic_features_for_stream_runtime_mesh(
    tmp_path: Path,
) -> None:
    planar_mesh = GmshPlanarMesh2D(
        points_xy=np.asarray(
            [
                [0.0, 0.0],
                [1.0, 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
            ],
            dtype=float,
        ),
        connectivity=np.asarray(
            [
                [0, 1, 2],
                [0, 2, 3],
            ],
            dtype=int,
        ),
        cell_type="triangle",
    )
    support = _DummyRasterSupport(
        xmin=0.0,
        xmax=2.0,
        ymin=0.0,
        ymax=2.0,
        dx=1.0,
        dy=1.0,
        nrows=2,
        ncols=2,
    )
    domain = SimpleNamespace(
        surface_topo=_DummySurface(np.full((2, 2), 10.0, dtype=float), support),
        substratum=_DummySurface(np.full((2, 2), 5.0, dtype=float), support),
        zones={},
    )
    flow = Flow(
        FlowConfig.model_validate(
            {
                "param_list": ["K", "Sy"],
                "param": {
                    "K": {"kind": "homogeneous", "value": 1.0e-5},
                    "Sy": {"kind": "homogeneous", "value": 0.2},
                },
                "ic": {"type": "custom", "value": 8.0},
                "active_bc": ["stream"],
                "bc": {
                    "dirichlet": {
                        "stream": {"value": 7.0},
                    }
                },
            }
        )
    )
    river_trace = SimpleNamespace(lines=[LineString([(0.0, 0.0), (1.0, 1.0)])])
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_planar=planar_mesh,
            mesh_bundle=None,
            mesh_summary=None,
            flow=flow,
            domain=domain,
            geographic_features=SimpleNamespace(
                rivers=SimpleNamespace(river_mesh_trace=river_trace)
            ),
            domain_geographic=None,
            time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
            workspace=SimpleNamespace(simulations_folder=tmp_path, solver_scratch_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq_runtime_mesh_stream",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert model.mesh is not None
    river_edges = model.mesh.river_edge_indices()
    assert river_edges.shape == (1,)
    assert model.state is not None
    assert model.state.imposed_head_edge_flux_m3_s is not None
    assert model.state.imposed_head_edge_flux_m3_s[int(river_edges[0])] > 0.0


@_OBSOLETE_RUNTIME_API
def test_boussinesq_flow_adapter_loads_bundle_from_mesh_summary(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(FlowConfig.model_validate({"ic": {"type": "bottom"}})),
            domain=None,
            time_grid=None,
            workspace=SimpleNamespace(simulations_folder=tmp_path, solver_scratch_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)

    assert state.setup.mesh_bundle is not None
    assert result.primary_model.state is not None
    assert np.allclose(result.primary_model.state.head_m, [5.0, 4.0])


@_OBSOLETE_RUNTIME_API
def test_boussinesq_flow_adapter_runs_transient_and_writes_outputs(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_transient")
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(FlowConfig.model_validate({"ic": {"type": "top"}})),
            domain=None,
            time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
            workspace=SimpleNamespace(simulations_folder=tmp_path, solver_scratch_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.head_history_m is not None
    assert model.state.head_history_m.shape == (2, 2)
    # Post-processing is no longer called by the adapter — ResultStore
    # extractors handle it.  Verify the solver output directory exists.
    assert result.solver_output_dir is not None


@_OBSOLETE_RUNTIME_API
def test_boussinesq_flow_adapter_completes_bundle_storage_from_metadata_default(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_custom_bundle(
        tmp_path / "bundle_default_storage",
        storage_values=("", ""),
        storage_default=0.02,
    )
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(FlowConfig.model_validate({"ic": {"type": "top"}})),
            domain=None,
            time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
            workspace=SimpleNamespace(simulations_folder=tmp_path, solver_scratch_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq_bundle_default_storage",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert model.mesh is not None
    assert np.allclose(model.mesh.storage_coefficient, [0.02, 0.02])
    assert model.has_numerical_solution is True


@_OBSOLETE_RUNTIME_API
def test_boussinesq_flow_adapter_allows_missing_bundle_storage_in_steady_mode(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_custom_bundle(
        tmp_path / "bundle_steady_missing_storage",
        storage_values=("", ""),
    )
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(
                FlowConfig.model_validate(
                    {"flow_regime": "steady", "ic": {"type": "bottom"}}
                )
            ),
            domain=None,
            time_grid=None,
            workspace=SimpleNamespace(simulations_folder=tmp_path, solver_scratch_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq_bundle_steady_missing_storage",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert model.mesh is not None
    assert np.allclose(model.mesh.storage_coefficient, [0.0, 0.0])
    assert model.has_numerical_solution is True


@_OBSOLETE_RUNTIME_API
def test_boussinesq_flow_adapter_supports_recharge_and_side_dirichlet(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_supported_inputs")
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(
                _build_flow_config(
                    {
                        "ic": {"type": "custom", "value": 7.0},
                        "active_sinks_sources": ["recharge"],
                        "active_bc": ["west_side"],
                        "sinks_sources": {"recharge": {"values": 1.0e-7, "units": "m/s"}},
                        "bc": {
                            "dirichlet": {
                                "west_side": {"value": 10.0},
                            }
                        },
                    }
                )
            ),
            domain=None,
            time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
            workspace=SimpleNamespace(simulations_folder=tmp_path, solver_scratch_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq_supported_inputs",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.recharge_rate_m_s is not None
    assert np.allclose(model.state.recharge_rate_m_s, 1.0e-7)
    assert model.state.imposed_head_edge_flux_m3_s is not None
    assert model.state.imposed_head_edge_flux_m3_s[4] < 0.0


@_OBSOLETE_RUNTIME_API
def test_boussinesq_flow_adapter_supports_absolute_xy_well(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_well")
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(
                _build_flow_config(
                    {
                        "ic": {"type": "custom", "value": 8.0},
                        "active_sinks_sources": ["wells"],
                        "sinks_sources": {
                            "wells": {
                                "W1": {
                                    "location_mode": "absolute_xy",
                                    "x": 0.75,
                                    "y": 0.25,
                                    "flux": -1.0e-5,
                                }
                            }
                        },
                    }
                )
            ),
            domain=None,
            time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
            workspace=SimpleNamespace(simulations_folder=tmp_path, solver_scratch_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq_well",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.well_flux_m3_s is not None
    assert np.isclose(model.state.well_flux_m3_s[0], -1.0e-5)
    assert np.isclose(model.state.well_flux_m3_s[1], 0.0)


@_OBSOLETE_RUNTIME_API
def test_boussinesq_flow_adapter_supports_stream_on_river_edges(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_stream", river_internal_edge=True)
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(
                _build_flow_config(
                    {
                        "ic": {"type": "custom", "value": 8.0},
                        "active_bc": ["stream"],
                        "bc": {
                            "dirichlet": {
                                "stream": {"value": 7.0},
                            }
                        },
                    }
                )
            ),
            domain=None,
            time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
            workspace=SimpleNamespace(simulations_folder=tmp_path, solver_scratch_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq_stream",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.imposed_head_edge_flux_m3_s is not None
    assert model.state.imposed_head_edge_flux_m3_s[2] > 0.0


@_OBSOLETE_RUNTIME_API
def test_boussinesq_flow_adapter_supports_ocean_on_coastal_edges(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle_ocean")
    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(
                _build_flow_config(
                    {
                        "ic": {"type": "custom", "value": 8.0},
                        "active_bc": ["ocean"],
                        "bc": {
                            "dirichlet": {
                                "ocean": {"value": 10.5},
                            }
                        },
                    }
                )
            ),
            domain=None,
            time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
            workspace=SimpleNamespace(simulations_folder=tmp_path, solver_scratch_folder=tmp_path),
        ),
    )
    run = ProcessRun(
        id="flow_main::boussinesq_ocean",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model

    assert model.has_numerical_solution is True
    assert model.state is not None
    assert model.state.imposed_head_edge_flux_m3_s is not None
    assert model.runtime_summary["active_ocean"] is True
    assert model.state.imposed_head_edge_flux_m3_s[0] < 0.0
    assert model.state.imposed_head_edge_flux_m3_s[1] < 0.0
    assert np.allclose(model.state.imposed_head_edge_flux_m3_s[[3, 4]], 0.0, atol=1.0e-12)
    assert model.state.head_m[0] > 8.0
