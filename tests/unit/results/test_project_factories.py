"""Smoke tests for :class:`hydromodpy.Project` factory entry points.

S05-10 adds ``from_toml`` / ``from_json`` / ``from_dict`` so callers reach
the :class:`Project` facade through a single uniform API.

The model phase is heavy (workspace, geographic, mesh) so these tests
monkey-patch :func:`project_phases.configure` and the eager phase verbs.
The aim is to verify the factories dispatch the right config payload to
``Project.__init__``, not to exercise the full pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_TOML_TEMPLATE = """\
workflow = "simulation"

[workspace]
root = "{root}"
project_root = "{root}"

[geographic]
source_mode = "synthetic"
"""


@pytest.fixture
def stub_project_phases(monkeypatch):
    """Replace heavy model-phase verbs with no-ops that record the config."""
    from hydromodpy import project_phases

    captured: dict[str, Any] = {}

    def _fake_configure(project, config, *, solver, headless, no_display):
        captured["config"] = config
        captured["solver"] = solver
        captured["headless"] = headless
        captured["no_display"] = no_display
        project.cfg = config if not isinstance(config, (str, Path)) else None
        project._config_path = Path(config).resolve() if isinstance(config, (str, Path)) else None

    monkeypatch.setattr(project_phases, "configure", _fake_configure)
    monkeypatch.setattr(project_phases, "build_geographic", lambda *_a, **_k: None)
    monkeypatch.setattr(project_phases, "load_data", lambda *_a, **_k: None)
    monkeypatch.setattr(project_phases, "build_mesh", lambda *_a, **_k: None)
    return captured


def _write_minimal_toml(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(_TOML_TEMPLATE.format(root=tmp_path.as_posix()), encoding="utf-8")
    return path


def _build_payload(tmp_path: Path) -> dict:
    return {
        "workflow": "simulation",
        "workspace": {
            "project_root": str(tmp_path),
            "root": str(tmp_path),
        },
        "geographic": {"source_mode": "synthetic"},
    }


def test_project_from_toml_passes_path_to_configure(
    tmp_path: Path,
    stub_project_phases: dict,
) -> None:
    from hydromodpy.project import Project

    config_path = _write_minimal_toml(tmp_path)
    Project.from_toml(config_path)
    assert stub_project_phases["config"] == config_path


def test_project_from_dict_validates_and_passes_config(
    tmp_path: Path,
    stub_project_phases: dict,
) -> None:
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.project import Project

    payload = _build_payload(tmp_path)
    Project.from_dict(payload)
    assert isinstance(stub_project_phases["config"], HydroModPyConfig)


def test_project_from_json_validates_and_passes_config(
    tmp_path: Path,
    stub_project_phases: dict,
) -> None:
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.project import Project

    payload = json.dumps(_build_payload(tmp_path))
    Project.from_json(payload)
    assert isinstance(stub_project_phases["config"], HydroModPyConfig)
