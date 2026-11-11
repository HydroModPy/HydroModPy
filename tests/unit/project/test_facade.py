"""A project opened on its directory reads without a configuration, and configures on demand.

``hmp.open(project)`` builds a :class:`~hydromodpy.project.Project` from its
directory alone (:func:`~hydromodpy.project.facade.open_project`). Its reads
(``root``, ``cases``, ``runs``, ``proj[ref]``) never validate a
configuration nor build a model; the first model verb reads ``project.toml``.

The facade also stays thin: its instance methods stay under a limit and it keeps the
canonical run-phase verbs.
"""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.core.exceptions import ConfigMissingError
from hydromodpy.project import Project
from hydromodpy.project.facade import open_project
from tests._helpers.sealed_runs import make_project, seal_run


class _StandInConfig(SimpleNamespace):
    """A stand-in configuration that ``Project.config`` can copy."""

    def model_copy(self, *, deep: bool = False) -> _StandInConfig:
        return copy.deepcopy(self)


@pytest.fixture
def configure_calls(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Replace the configuration step by a recorder that sets a stand-in config."""
    calls: list[Path] = []

    def configure(project: Project, config: Any, **_kwargs: Any) -> None:
        calls.append(Path(config))
        project._config_path = Path(config)
        project._cfg = _StandInConfig(simulation=SimpleNamespace(name="baseline"))

    monkeypatch.setattr("hydromodpy.project.phases.configure", configure)
    return calls


@pytest.mark.fast
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


@pytest.mark.fast
def test_the_first_model_read_configures_from_project_toml_once(
    tmp_path: Path, configure_calls: list[Path]
) -> None:
    project = make_project(tmp_path / "p")
    proj = open_project(project)

    assert proj.config.simulation.name == "baseline"
    assert proj.config.simulation.name == "baseline"
    assert configure_calls == [(project / "project.toml").resolve()]


@pytest.mark.fast
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


@pytest.mark.fast
def test_a_folder_without_project_toml_reads_but_builds_no_model(tmp_path: Path) -> None:
    project = tmp_path / "flat"
    seal_run(project, "baseline")

    proj = open_project(project)

    assert list(proj.cases["case_id"]) == ["baseline"]
    with pytest.raises(ConfigMissingError, match="project.toml"):
        proj.config  # noqa: B018


@pytest.mark.fast
def test_a_project_built_from_a_config_keeps_its_root_from_the_config(tmp_path: Path) -> None:
    from hydromodpy.project.state import ProjectState

    configured = SimpleNamespace(workspace=SimpleNamespace(project_root=tmp_path / "x"))
    project = object.__new__(Project)
    object.__setattr__(project, "_state", ProjectState(cfg=configured))

    assert project.root == (tmp_path / "x").resolve()
    assert project._state.root is None


@pytest.mark.fast
def test_project_gc_plans_without_touching_the_tree(
    tmp_path: Path, configure_calls: list[Path]
) -> None:
    import hashlib

    from hydromodpy.results.products.store import ProductStore, products_root
    from hydromodpy.results.retention import project_weight

    project = make_project(tmp_path / "p")
    (project / "project.toml").write_text("[workspace]\nproducts_cap_mb = 1\n", encoding="utf-8")
    key = hashlib.sha256(b"product").hexdigest()
    store = ProductStore(products_root(project))
    store.put(key, "mesh", lambda folder: (folder / "blob").write_bytes(b"x" * 1_500_000))
    before = project_weight(project)

    with open_project(project) as proj:
        report = proj.gc(dry_run=True)

    assert report.applied is False
    assert report.freed == {}
    assert report.plan.products, "the cap of project.toml is read from its [workspace] section"
    assert store.get(key) is not None
    assert project_weight(project) == before
    assert configure_calls == []


MAX_PROJECT_METHODS = 19


def test_project_instance_methods_below_limit() -> None:
    """Project keeps a small public method surface."""
    methods = [
        name
        for name, value in vars(Project).items()
        if callable(value) and not name.startswith("_") and not isinstance(value, classmethod)
    ]
    assert len(methods) <= MAX_PROJECT_METHODS, (
        f"Project has {len(methods)} instance methods (max {MAX_PROJECT_METHODS}): {methods}"
    )


def test_project_drops_removed_surface() -> None:
    """The removed run/session/factory surface is gone."""
    for name in (
        "lazy",
        "session",
        "from_toml",
        "from_json",
        "from_dict",
        "ingest",
        "render",
        "cleanup",
    ):
        assert not hasattr(Project, name), f"Project still exposes removed {name!r}"


def test_project_keeps_canonical_run_phase_verbs() -> None:
    """``Project`` keeps the high-level run-phase verbs and the launch verbs of a project."""
    for name in ("simulate", "calibrate", "prepare", "rerun", "plan", "launch", "collect"):
        assert hasattr(Project, name), f"Project lost canonical verb {name!r}"


def test_project_config_is_a_property() -> None:
    """``cfg`` is replaced by the read-only ``config`` property."""
    assert isinstance(Project.config, property)
    assert not hasattr(Project, "cfg")


def test_project_drops_toml_only_workflow_verbs() -> None:
    """TOML-only workflows live on ``hmp._api``, not on ``Project``."""
    for name in ("overview", "compare", "mesh", "report"):
        assert not hasattr(Project, name), (
            f"Project still exposes {name!r}; the canonical entry point is hmp.{name}()"
        )


def test_project_keeps_model_phase_verbs() -> None:
    """``Project`` keeps the model-phase verbs that mutate the context."""
    for name in (
        "setup_workspace",
        "build_geographic",
        "load_data",
        "reload_data",
        "rebuild_geographic",
        "build_mesh",
    ):
        assert hasattr(Project, name), f"Project lost model-phase verb {name!r}"


# --- A document in memory is read against the base the caller names ---

SYNTHETIC = {"workflow": {"mode": "simulation"}, "geographic": {"source_mode": "synthetic"}}


def test_a_document_in_memory_is_read_against_the_base_and_never_the_current_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.project.facade import resolve_config

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    base = tmp_path / "project"
    base.mkdir()

    loaded = resolve_config(SYNTHETIC, base)

    assert isinstance(loaded, HydroModPyConfig)
    assert loaded.workspace.project_root == base.resolve()
    with pytest.raises(ConfigError, match="needs base="):
        resolve_config(SYNTHETIC, None)
    with pytest.raises(ConfigError, match="needs base="):
        resolve_config('{"workflow": {"mode": "simulation"}}', None)


def test_a_path_and_a_built_configuration_pass_through_the_resolver(tmp_path: Path) -> None:
    from hydromodpy.project.facade import resolve_config

    built = object()
    assert resolve_config(built, None) is built
    assert resolve_config(tmp_path / "project.toml", None) == tmp_path / "project.toml"


def test_a_sealed_snapshot_names_its_own_project_root(tmp_path: Path) -> None:
    from hydromodpy.project.facade import read_sealed_config

    snapshot = {**SYNTHETIC, "workspace": {"project_root": str(tmp_path)}}

    cfg = read_sealed_config(snapshot)

    assert cfg.workspace.project_root == tmp_path.resolve()
    assert cfg.read_as_sealed is True
