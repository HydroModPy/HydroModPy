"""Smoke tests for the polymorphic :class:`hydromodpy.Project` constructor.

``Project(config)`` accepts a TOML path, a ``HydroModPyConfig``, a ``dict``,
or a JSON string (auto-detected) - replacing the removed ``from_toml`` /
``from_json`` / ``from_dict`` factories.

The model phase is heavy (workspace, geographic, mesh) so these tests
monkey-patch :func:`project_phases.configure`. The aim is to verify the
constructor dispatches the right config payload to ``configure``, not to
exercise the full pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_TOML_TEMPLATE = """\
[workflow]
mode = "simulation"

[workspace]
root = "{root}"

[geographic]
source_mode = "synthetic"
"""


@pytest.fixture
def stub_project_phases(monkeypatch, tmp_path):
    """Replace heavy model-phase verbs with no-ops that record the config."""
    from hydromodpy.project import phases as project_phases

    captured: dict[str, Any] = {}

    def _fake_configure(
        project,
        config,
        *,
        solver,
        headless,
        no_display,
        environment=None,
        base=None,
        document=None,
        source=None,
    ):
        captured["config"] = config
        captured["base"] = base
        captured["document"] = document
        captured["solver"] = solver
        captured["headless"] = headless
        captured["no_display"] = no_display
        captured["environment"] = environment
        # The constructor checks the Environment against the project root,
        # so a config the stub does not build still names one.
        stand_in = SimpleNamespace(workspace=SimpleNamespace(project_root=tmp_path, root=None))
        project._cfg = config if hasattr(config, "workspace") else stand_in
        project._config_path = Path(config).resolve() if isinstance(config, (str, Path)) else None
        project._ctx = SimpleNamespace(parent_sim_id=None)

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
        "workflow": {"mode": "simulation"},
        "workspace": {"root": str(tmp_path)},
        "geographic": {"source_mode": "synthetic"},
    }


def test_project_constructor_passes_path_to_configure(
    tmp_path: Path,
    stub_project_phases: dict,
) -> None:
    from hydromodpy.project.facade import Project

    config_path = _write_minimal_toml(tmp_path)
    Project(config_path)
    assert stub_project_phases["config"] == config_path


def test_project_constructor_validates_dict(
    tmp_path: Path,
    stub_project_phases: dict,
) -> None:
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.project.facade import Project

    payload = _build_payload(tmp_path)
    Project(payload, base=tmp_path)
    assert isinstance(stub_project_phases["config"], HydroModPyConfig)
    assert stub_project_phases["config"].workspace.project_root == tmp_path.resolve()
    assert stub_project_phases["document"] == payload, "the planner reads the document as given"


def test_project_constructor_refuses_a_dict_without_a_base(
    tmp_path: Path,
    stub_project_phases: dict,
) -> None:
    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.project.facade import Project

    with pytest.raises(ConfigError, match="needs base="):
        Project(_build_payload(tmp_path))
    assert "config" not in stub_project_phases


def test_project_constructor_validates_json_string(
    tmp_path: Path,
    stub_project_phases: dict,
) -> None:
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.project.facade import Project

    payload = json.dumps(_build_payload(tmp_path))
    Project(payload, base=tmp_path)
    assert isinstance(stub_project_phases["config"], HydroModPyConfig)
    assert stub_project_phases["base"] == tmp_path.resolve()


def test_project_rerun_builds_from_snapshot_and_delegates_parent(
    monkeypatch,
    stub_project_phases: dict,
) -> None:
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.project.facade import Project

    cfg = object()
    captured: dict[str, Any] = {}

    def _fake_from_snapshot(cls, snapshot, *, changes=None):
        captured["snapshot"] = snapshot
        captured["changes"] = changes
        return cfg

    def _fake_simulate(self, *, name=None, lineage=None):
        captured["name"] = name
        captured["parent_sim_id"] = self._ctx.parent_sim_id
        captured["lineage"] = lineage
        return SimpleNamespace(sim_id="child")

    monkeypatch.setattr(HydroModPyConfig, "from_snapshot", classmethod(_fake_from_snapshot))
    monkeypatch.setattr(Project, "simulate", _fake_simulate)

    parent = SimpleNamespace(
        sim_id="parent",
        dir=None,
        config_snapshot={"workflow": {"mode": "simulation"}},
    )

    child = Project.rerun(parent, name="derived", set={"display.save": False})

    assert child.sim_id == "child"
    assert stub_project_phases["config"] is cfg
    assert captured["snapshot"] == {"workflow": {"mode": "simulation"}}
    assert captured["changes"] == {"display.save": False}
    assert captured["name"] == "derived"
    assert captured["parent_sim_id"] == "parent"
    assert captured["lineage"].kind == "rerun"
    assert captured["lineage"].overrides == {"display.save": False}
