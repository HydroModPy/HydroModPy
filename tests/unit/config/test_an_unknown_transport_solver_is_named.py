"""A transport solver name that is neither built in nor a plugin is refused by name.

The name used to pass validation, and the run failed later.
"""

from __future__ import annotations

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig


def _config(tmp_path, transport: str) -> HydroModPyConfig:
    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        simulation={
            "process": [
                {"id": "flow_main", "type": "flow", "solvers": ["modflow6"]},
                {"id": "transport_main", "type": "transport", "solvers": [transport]},
            ]
        },
    )


def test_an_unknown_transport_solver_is_refused_with_the_valid_names(tmp_path) -> None:
    with pytest.raises(ValueError) as excinfo:
        _config(tmp_path, "modpth")
    message = str(excinfo.value)
    assert "Unknown transport solver 'modpth'" in message
    assert "[[simulation.process]]" in message
    assert "modpath" in message
    assert "modflow6_prt" in message


def test_a_built_in_transport_solver_is_accepted(tmp_path) -> None:
    cfg = _config(tmp_path, "modflow6_prt")
    assert cfg.simulation.process[1].solvers == ["modflow6_prt"]
