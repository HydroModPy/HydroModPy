"""Config fixtures for the test suite.

Provides reusable :class:`~hydromodpy.config.HydroModPyConfig`
instances covering minimal, flow-oriented, and calibration-oriented
scenarios. Each builder accepts an explicit ``project_root`` so callers
control workspace isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def minimal_hmp_config(project_root: Path):
    """Return a minimal valid :class:`HydroModPyConfig`.

    Only the two required subsections (``workspace`` and ``geographic``)
    are populated; all others fall back to their factory defaults.
    """
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.core.workspace.config import WorkspaceConfig
    from hydromodpy.spatial.geographic.geographic_config import GeographicConfig

    ws_root = Path(project_root)
    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(
            project_root=ws_root / "project",
            root=ws_root,
        ),
        geographic=GeographicConfig(source_mode="synthetic"),
    )


@pytest.fixture
def minimal_config(tmp_path: Path):
    """Minimal HydroModPy config rooted in ``tmp_path``."""
    return minimal_hmp_config(tmp_path)


@pytest.fixture
def flow_steady_config(tmp_path: Path):
    """HydroModPy config with a steady flow block pre-populated."""
    from hydromodpy.physics.flow.flow_config import FlowConfig

    cfg = minimal_hmp_config(tmp_path)
    return cfg.model_copy(update={"flow": FlowConfig(flow_regime="steady")})


@pytest.fixture
def flow_transient_config(tmp_path: Path):
    """HydroModPy config with a transient flow block pre-populated."""
    from hydromodpy.physics.flow.flow_config import FlowConfig

    cfg = minimal_hmp_config(tmp_path)
    return cfg.model_copy(update={"flow": FlowConfig(flow_regime="transient")})
