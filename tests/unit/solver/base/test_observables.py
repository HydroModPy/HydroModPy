"""Whether a flow backend can serve an observable, on the resolved configuration.

MODFLOW 6 hands back a lake stage, but only when the file declares a lake.
MODFLOW-NWT never can, because it builds no LAK package. A user who only had to
declare a lake must not be told to change backend, and the refusal must come
before the calibration search, not at its first trial.
"""

from __future__ import annotations

import importlib

import numpy as np

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.preflight import preflight_calibration
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.contracts.observables import ObservableRequest
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.solver.base.observables import ObservableSupport, scalar_observable
from hydromodpy.solver.base.solver_config import SolverConfig

LAKES = {"lakes": {"cheze": {"bedleak": 1e-6, "initial_stage": "10 m"}}}

ADAPTERS = {
    "modflow6": ("hydromodpy.solver.modflow6.adapter", "Modflow6FlowAdapter"),
    "modflow_nwt": ("hydromodpy.solver.modflow_nwt.adapter", "ModflowNwtFlowAdapter"),
    "boussinesq": ("hydromodpy.solver.boussinesq.adapter", "BoussinesqFlowAdapter"),
}


def config_for(tmp_path, backend: str, **flow: object) -> HydroModPyConfig:
    # Boussinesq reads triangles only: the validator refuses the default grid.
    mesh = MeshConfig(engine="triangle") if backend == "boussinesq" else None
    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        solver=SolverConfig(backend=backend),
        flow=FlowConfig(**flow),
        mesh=mesh,
    )


def declared_by(backend: str, cfg) -> dict[str, ObservableSupport]:
    module, cls = ADAPTERS[backend]
    adapter = getattr(importlib.import_module(module), cls)()
    active = frozenset(cfg.flow.active_bc or ())
    return {item.name: item for item in adapter.declared_observables(active)}


def test_declaring_the_lake_makes_its_stage_servable(tmp_path) -> None:
    declared = declared_by("modflow6", config_for(tmp_path, "modflow6", sinks_sources=LAKES))

    assert declared["stage"].is_servable_now


def test_lake_stage_is_never_servable_under_nwt(tmp_path) -> None:
    declared = declared_by("modflow_nwt", config_for(tmp_path, "modflow_nwt"))

    assert declared["stage"].can_never_be_served
    assert "LAK" in declared["stage"].reason


def test_preflight_refuses_a_network_output_on_boussinesq(tmp_path) -> None:
    (tmp_path / "net.gpkg").write_bytes(b"")
    cfg = config_for(
        tmp_path,
        "boussinesq",
        param_list=["K"],
        param={"K": {"field": {"id": "K", "kind": "homogeneous", "unit": "m/s", "value": 1e-5}}},
    )
    cfg.calibration = CalibrationConfig.model_validate(
        {
            "parameters": {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}},
            "outputs": {
                "target": {"support": "network", "map": {"complete": str(tmp_path / "net.gpkg")}}
            },
            "objective_blocks": [
                {"name": "b", "metric": "distance_gap", "uses_outputs": ["target"]}
            ],
        }
    )

    findings = preflight_calibration(cfg, source=tmp_path / "calib.toml")

    messages = " | ".join(f"{item.path}: {item.detail}" for item in findings)
    assert "release_flux" in messages
    assert "MODFLOW" in messages


def test_scalar_observable_is_a_zero_dimensional_array() -> None:
    request = ObservableRequest(id="k_mean", name="K", support="cell", cell=(0, 0, 0))

    result = scalar_observable(request, 2.5e-5, units="m s-1")  # a float or an int alike

    assert result.request_id == "k_mean"
    assert result.values.shape == ()
    assert result.values.dtype == np.float64
    np.testing.assert_allclose(result.values, 2.5e-5, rtol=0)
    assert result.units == "m s-1"
    assert result.times is None
