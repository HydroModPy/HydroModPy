from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.properties.field_spatial import WeightedAverageFieldDiscretization
from hydromodpy.solver.base.plan import ProcessRun, RunContext, SimulationPlan
from hydromodpy.solver.base.registry import get_solver_adapter
from hydromodpy.solver.boussinesq.adapters.flow import BoussinesqFlowAdapter
from tests._helpers.cell_meshes import cell_mesh_of

from ._test_boussinesq_flow_adapter_builders import (
    _DummyRasterSupport,
    _DummySurface,
    _homogeneous_param,
    _write_custom_bundle,
    _write_minimal_bundle,
    adapter_state,
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

    def on_mesh(self, cell_mesh, *, cell_samples_per_axis: int = 10):
        _ = cell_samples_per_axis
        x_centers = np.asarray(cell_mesh.centers[:, 0], dtype=float)
        midpoint = 0.5 * (float(np.min(x_centers)) + float(np.max(x_centers)))
        west = (x_centers <= midpoint).astype(float)
        east = 1.0 - west
        return WeightedAverageFieldDiscretization(
            mesh=cell_mesh,
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
    planar_mesh = HydroMesh(
        vertices=np.asarray([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=float),
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray([[0, 1, 2], [0, 2, 3]])),),
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
                "ic": {"kind": "bottom"},
            }
        )
    )
    state = adapter_state(tmp_path, flow=flow, cell_mesh=cell_mesh_of(planar_mesh), domain=domain)
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
    planar_mesh = HydroMesh(
        vertices=np.asarray([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=float),
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray([[0, 1, 2], [0, 2, 3]])),),
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
                "ic": {"kind": "bottom"},
            }
        )
    )
    state = adapter_state(tmp_path, flow=flow, cell_mesh=cell_mesh_of(planar_mesh), domain=domain)
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


def _bundle_context(
    tmp_path: Path, *, bundle_dir: Path, flow: Flow, **model_parts: object
) -> RunContext:
    state = adapter_state(
        tmp_path,
        flow=flow,
        mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
        time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
        **model_parts,
    )
    run = ProcessRun(
        id="flow_main::boussinesq_bundle",
        process_id="flow_main",
        process_type="flow",
        solver="boussinesq",
    )
    return RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )


def test_boussinesq_flow_adapter_refuses_a_flow_k_next_to_the_k_of_a_bundle(
    tmp_path: Path,
) -> None:
    """The bundle cells carry K and [flow.param.K] sets it too: two sources, refused.

    The runtime mesh cannot be built here (the domain has no surface), so the
    adapter falls back to the bundle. Before, the flow K mapped on the runtime
    mesh overwrote the bundle K in silence.
    """
    planar_mesh = HydroMesh(
        vertices=np.asarray([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=float),
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray([[0, 1, 2], [0, 2, 3]])),),
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
                "ic": {"kind": "top"},
            }
        )
    )
    ctx = _bundle_context(
        tmp_path,
        bundle_dir=bundle_dir,
        flow=flow,
        cell_mesh=cell_mesh_of(planar_mesh),
        domain=SimpleNamespace(
            zones={"field_hydrofacies": _HalfDomainSupport("field_hydrofacies")}
        ),
    )

    with pytest.raises(ValueError, match=r"Two sources set K") as error:
        BoussinesqFlowAdapter().execute(ctx)
    assert str(bundle_dir) in str(error.value)
    assert "[flow.param.K]" in str(error.value)


def test_boussinesq_flow_adapter_refuses_a_flow_k_next_to_a_bundle_default_k(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_custom_bundle(
        tmp_path / "bundle_default_k",
        conductivity_values=("", ""),
        conductivity_default=3.0e-5,
    )
    flow = Flow(
        FlowConfig.model_validate(
            {"param_list": ["K"], "param": {"K": _homogeneous_param(1.0e-5)}, "ic": {"kind": "top"}}
        )
    )

    with pytest.raises(ValueError, match=r"Two sources set K"):
        BoussinesqFlowAdapter().execute(_bundle_context(tmp_path, bundle_dir=bundle_dir, flow=flow))


def test_boussinesq_flow_adapter_never_maps_a_flow_k_on_a_bundle(tmp_path: Path) -> None:
    bundle_dir = _write_custom_bundle(tmp_path / "bundle_no_k", conductivity_values=("", ""))
    flow = Flow(
        FlowConfig.model_validate(
            {"param_list": ["K"], "param": {"K": _homogeneous_param(1.0e-5)}, "ic": {"kind": "top"}}
        )
    )

    with pytest.raises(ValueError, match=r"cannot be mapped on the mesh bundle"):
        BoussinesqFlowAdapter().execute(_bundle_context(tmp_path, bundle_dir=bundle_dir, flow=flow))


def test_boussinesq_flow_adapter_completes_bundle_k_from_metadata_default(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_custom_bundle(
        tmp_path / "bundle_default_k_only",
        conductivity_values=("", "4.0e-5"),
        conductivity_default=3.0e-5,
    )
    flow = Flow(FlowConfig.model_validate({"ic": {"kind": "top"}}))

    result = BoussinesqFlowAdapter().execute(
        _bundle_context(tmp_path, bundle_dir=bundle_dir, flow=flow)
    )

    assert np.allclose(result.primary_model.mesh.hydraulic_conductivity_m_s, [3.0e-5, 4.0e-5])


def test_boussinesq_flow_adapter_loads_bundle_from_mesh_summary(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_bundle(tmp_path / "bundle")
    state = adapter_state(
        tmp_path,
        flow=Flow(FlowConfig.model_validate({"ic": {"kind": "bottom"}})),
        mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
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
    state = adapter_state(
        tmp_path,
        flow=Flow(FlowConfig.model_validate({"ic": {"kind": "top"}})),
        mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
        time_grid=SimpleNamespace(period_lengths_seconds=(3600.0,)),
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
    state = adapter_state(
        tmp_path,
        flow=Flow(FlowConfig.model_validate({"flow_regime": "steady", "ic": {"kind": "bottom"}})),
        mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
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
