"""Wells declared without "wells" in active_sinks_sources are refused.

Every backend builds its wells only when flow.active_sinks_sources lists
them. A declared well that is not listed would pump nothing, silently.
"""

from __future__ import annotations

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig

_WELL = {"W1": {"flux": -0.01, "location": {"kind": "relative_xy", "x_rel": 0.5, "y_rel": 0.5}}}


def _config(tmp_path, active: list[str]) -> HydroModPyConfig:
    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        flow=FlowConfig(active_sinks_sources=active, sinks_sources={"wells": _WELL}),
    )


def test_wells_without_activation_are_refused(tmp_path) -> None:
    with pytest.raises(ValueError, match=r"declares wells \(W1\).*does not list 'wells'"):
        _config(tmp_path, ["recharge"])


def test_wells_with_activation_are_accepted(tmp_path) -> None:
    cfg = _config(tmp_path, ["recharge", "wells"])
    assert "W1" in cfg.flow.sinks_sources.wells
