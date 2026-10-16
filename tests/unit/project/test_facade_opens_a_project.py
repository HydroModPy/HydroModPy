"""A project opened on its directory reads without a configuration, and configures on demand.

``hmp.open(project)`` builds a :class:`~hydromodpy.project.Project` from its
directory alone (:func:`~hydromodpy.project.facade.open_project`). Its reads
(``root``, ``cases``, ``runs``, ``proj[ref]``) never validate a
configuration nor build a model; the first model verb reads ``project.toml``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.core.exceptions import ConfigMissingError
from hydromodpy.project import Project
from hydromodpy.project.facade import open_project
from tests._helpers.sealed_runs import make_project, seal_run

pytestmark = pytest.mark.fast


@pytest.fixture
def configure_calls(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Replace the configuration step by a recorder that sets a stand-in config."""
    calls: list[Path] = []

    def configure(project: Project, config: Any, **_kwargs: Any) -> None:
        calls.append(Path(config))
        project._config_path = Path(config)
        project._cfg = SimpleNamespace(simulation=SimpleNamespace(name="baseline"))

    monkeypatch.setattr("hydromodpy.project.phases.configure", configure)
    return calls


def test_reading_an_opened_project_never_configures_it(
    tmp_path: Path, configure_calls: list[Path]
) -> None:
    project = make_project(tmp_path / "p")
    sim_id = seal_run(project, "baseline")

    with open_project(project / "project.toml") as proj:
        assert proj.root == project.resolve()
        assert list(proj.cases["rel_dir"]) == ["runs/baseline"]
        assert proj.runs().sim_ids == [sim_id]
        assert proj["baseline"].sim_id == sim_id
        assert repr(proj) == f"Project({str(project.resolve())!r})"
        assert "Project" in proj._repr_html_()

    assert configure_calls == []


def test_the_first_model_read_configures_from_project_toml_once(
    tmp_path: Path, configure_calls: list[Path]
) -> None:
    project = make_project(tmp_path / "p")
    proj = open_project(project)

    assert proj.config.simulation.name == "baseline"
    assert proj.config.simulation.name == "baseline"
    assert configure_calls == [(project / "project.toml").resolve()]


def test_a_configuration_that_fails_is_tried_again_on_the_next_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def configure(project: Project, config: Any, **_kwargs: Any) -> None:
        project._cfg = object()
        raise ValueError("bad config")

    monkeypatch.setattr("hydromodpy.project.phases.configure", configure)
    proj = open_project(make_project(tmp_path / "p"))

    for _ in range(2):
        with pytest.raises(ValueError, match="bad config"):
            proj.config  # noqa: B018
    assert proj._state.cfg is None


def test_a_folder_without_project_toml_reads_but_builds_no_model(tmp_path: Path) -> None:
    project = tmp_path / "flat"
    seal_run(project, "baseline")

    proj = open_project(project)

    assert list(proj.cases["case_id"]) == ["baseline"]
    with pytest.raises(ConfigMissingError, match="project.toml"):
        proj.config  # noqa: B018


def test_a_project_built_from_a_config_keeps_its_root_from_the_config(tmp_path: Path) -> None:
    from hydromodpy.project.state import ProjectState

    configured = SimpleNamespace(workspace=SimpleNamespace(project_root=tmp_path / "x"))
    project = object.__new__(Project)
    object.__setattr__(project, "_state", ProjectState(cfg=configured))

    assert project.root == (tmp_path / "x").resolve()
    assert project._state.root is None
