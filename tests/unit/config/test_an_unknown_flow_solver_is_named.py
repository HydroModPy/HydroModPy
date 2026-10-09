"""A flow solver name that is neither built in nor a plugin is refused by name.

The name used to become a custom backend, and the first capability check
refused it with a message about the drainage boundary.
"""

from __future__ import annotations

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.solver.base import registry
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig


def _config(tmp_path, solver: str, active_bc: list[str]) -> HydroModPyConfig:
    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        simulation={"process": [{"id": "flow_main", "type": "flow", "solvers": [solver]}]},
        flow=FlowConfig(active_bc=active_bc),
    )


def test_an_unknown_flow_solver_is_refused_with_the_valid_names(tmp_path) -> None:
    with pytest.raises(ValueError) as excinfo:
        _config(tmp_path, "modflow7", ["drainage"])
    message = str(excinfo.value)
    assert "Unknown flow solver 'modflow7'" in message
    assert "neither built in nor a registered plugin" in message
    assert "modflow6, modflow_nwt" in message
    assert "drainage" not in message


def test_a_registered_plugin_flow_solver_is_accepted(tmp_path) -> None:
    class _Adapter:
        process_type = "flow"
        solver_name = "pluginflow"
        requires: tuple[tuple[str, str], ...] = ()

        def validate(self, ctx): ...

        def execute(self, ctx): ...

        def cleanup(self, ctx): ...

        def extract_observables(self, ctx, store, requests, **kwargs):
            return {}

    registry.register("flow", "pluginflow", _Adapter)
    try:
        cfg = _config(tmp_path, "pluginflow", [])
    finally:
        registry.unregister("flow", "pluginflow")
    assert cfg.solver.backend_name == "pluginflow"
