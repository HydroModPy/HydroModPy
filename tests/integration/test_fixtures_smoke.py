"""Smoke tests for the root-level tmp_workspace and minimal_config fixtures."""

from pathlib import Path

from hydromodpy.config import HydroModPyConfig


def test_tmp_workspace_creates_layout(tmp_workspace: Path) -> None:
    assert tmp_workspace.exists()
    assert (tmp_workspace / "data").is_dir()
    assert (tmp_workspace / "projects").is_dir()


def test_minimal_config_is_valid(minimal_config: HydroModPyConfig) -> None:
    assert isinstance(minimal_config, HydroModPyConfig)
    assert minimal_config.geographic.source_mode == "synthetic"
    assert minimal_config.workspace.project_root.name == "project"
