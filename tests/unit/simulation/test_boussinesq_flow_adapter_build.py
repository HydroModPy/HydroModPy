from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.physics.flow import Flow
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.simulation.planning.plan import (
    ProcessRun,
    RunContext,
    SimulationPlan,
)
from hydromodpy.solver.base.registry import get_solver_adapter
from hydromodpy.solver.boussinesq.adapters.flow import BoussinesqFlowAdapter
from hydromodpy.spatial.field.core.field_spatial_weighted_discretization import (
    WeightedAverageFieldDiscretization,
)
from hydromodpy.spatial.mesh.gmsh_grid import GmshPlanarMesh2D

from ._test_boussinesq_flow_adapter_builders import (
    _DummyRasterSupport,
    _DummySurface,
    _homogeneous_param,
    _write_custom_bundle,
    _write_minimal_bundle,
)


def _heterogeneous_param(values: dict[str, object], field_spatial_id: str) -> dict[str, object]:
    return {
        "field": {
            "kind": "heterogeneous",
            "values": values,
            "field_spatial_id": field_spatial_id,
        }
    }


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


def test_registry_exposes_boussinesq_flow_adapter() -> None:
    adapter = get_solver_adapter("flow", "boussinesq")

    assert isinstance(adapter, BoussinesqFlowAdapter)


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
                    "K": _homogeneous_param(1.0e-5),
                    "Sy": _homogeneous_param(0.2),
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
                    "K": _heterogeneous_param(
                        {"west": 2.0e-5, "east": 5.0e-6},
                        "field_geology",
                    ),
                    "Sy": _heterogeneous_param({"west": 0.22, "east": 0.08}, "field_geology"),
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
                    "K": _heterogeneous_param(
                        {"west": 3.0e-4, "east": 8.0e-7},
                        "field_hydrofacies",
                    ),
                    "Sy": _heterogeneous_param(
                        {"west": 0.21, "east": 0.03},
                        "field_hydrofacies",
                    ),
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
                FlowConfig.model_validate({"flow_regime": "steady", "ic": {"type": "bottom"}})
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
