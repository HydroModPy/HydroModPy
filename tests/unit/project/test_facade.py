"""A project opened on its directory reads without a configuration, and configures on demand.

``hmp.open(project)`` builds a :class:`~hydromodpy.project.facade.Project` from its
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
from hydromodpy.project.facade import Project, open_project
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
def test_reads_never_configure(tmp_path: Path, configure_calls: list[Path]) -> None:
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
def test_held_index_lock_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import hydromodpy.results.catalog.indexer as indexer
    from hydromodpy.core.exceptions import WriteConflictError

    project = make_project(tmp_path / "p")
    seal_run(project, "baseline")

    with open_project(project / "project.toml") as proj:
        first = proj._index()

        def held(root: Path, **_kwargs: object) -> None:
            raise WriteConflictError("The index is being written by process 1.")

        monkeypatch.setattr(indexer, "index_new_runs", held)
        with caplog.at_level("WARNING"):
            assert proj._index() is first
        assert "Index not refreshed" in caplog.text


@pytest.mark.fast
def test_first_read_under_lock(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    import time

    from hydromodpy.core.io.lock_file import LockFile
    from hydromodpy.results.catalog.index_file import index_lock_path

    project = make_project(tmp_path / "p")
    seal_run(project, "baseline")
    with open_project(project / "project.toml") as proj:
        assert list(proj.cases["rel_dir"]) == ["runs/baseline"]
    seal_run(project, "second")

    writer = LockFile(index_lock_path(project))
    assert writer.acquire() is True
    try:
        with open_project(project / "project.toml") as proj, caplog.at_level("WARNING"):
            started = time.monotonic()
            rel_dirs = list(proj.cases["rel_dir"])
            assert time.monotonic() - started < 10
        assert "runs/baseline" in rel_dirs
        assert "Index not refreshed" in caplog.text
    finally:
        writer.release()


@pytest.mark.fast
def test_publish_copies_summary(tmp_path: Path) -> None:
    import inspect
    import json

    project = make_project(tmp_path / "p")
    (project / "summary").mkdir()
    (project / "summary" / "notes.md").write_text("# Summary\n", encoding="utf-8")

    with open_project(project / "project.toml") as proj:
        assert "with_" not in inspect.signature(proj.publish).parameters
        with pytest.raises(TypeError):
            proj.publish(tmp_path / "refused", with_=("results",))  # type: ignore[call-arg]
        copy = proj.publish(tmp_path / "copy")

    assert (copy / "notes.md").read_text(encoding="utf-8") == "# Summary\n"
    publication = json.loads((copy / "PUBLICATION.json").read_text(encoding="utf-8"))
    assert publication["kind"] == "summary"
    assert publication["with"] == []
    assert not (tmp_path / "refused").exists()


@pytest.mark.fast
def test_config_loaded_once(tmp_path: Path, configure_calls: list[Path]) -> None:
    project = make_project(tmp_path / "p")
    proj = open_project(project)

    assert proj.config.simulation.name == "baseline"
    assert proj.config.simulation.name == "baseline"
    assert configure_calls == [(project / "project.toml").resolve()]


@pytest.mark.fast
def test_failed_config_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
def test_folder_without_project_toml(tmp_path: Path) -> None:
    project = tmp_path / "flat"
    seal_run(project, "baseline")

    proj = open_project(project)

    assert list(proj.cases["case_id"]) == ["baseline"]
    with pytest.raises(ConfigMissingError, match="project.toml"):
        proj.config  # noqa: B018


@pytest.mark.fast
def test_root_from_config(tmp_path: Path) -> None:
    from hydromodpy.project.state import ProjectState

    configured = SimpleNamespace(workspace=SimpleNamespace(project_root=tmp_path / "x"))
    project = object.__new__(Project)
    object.__setattr__(project, "_state", ProjectState(cfg=configured))

    assert project.root == (tmp_path / "x").resolve()
    assert project._state.root is None


@pytest.mark.fast
def test_gc_dry_run_plans(tmp_path: Path, configure_calls: list[Path]) -> None:
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


def test_method_count_limit() -> None:
    methods = [
        name
        for name, value in vars(Project).items()
        if callable(value) and not name.startswith("_") and not isinstance(value, classmethod)
    ]
    assert len(methods) <= MAX_PROJECT_METHODS, (
        f"Project has {len(methods)} instance methods (max {MAX_PROJECT_METHODS}): {methods}"
    )


# Run, launch and model-phase verbs stay on the facade.
KEPT_VERBS = [
    pytest.param(
        ("simulate", "calibrate", "prepare", "rerun", "plan", "launch", "collect"), id="run phase"
    ),
    pytest.param(
        (
            "setup_workspace",
            "build_geographic",
            "load_data",
            "reload_data",
            "rebuild_geographic",
            "build_mesh",
        ),
        id="model phase",
    ),
]

# The old factories and the TOML-only workflows live elsewhere.
REMOVED_VERBS = [
    pytest.param(
        ("lazy", "session", "from_toml", "from_json", "from_dict", "ingest", "render", "cleanup"),
        id="old surface",
    ),
    pytest.param(("overview", "compare", "mesh", "report"), id="toml only workflows"),
]


@pytest.mark.parametrize("names", KEPT_VERBS)
def test_kept_verbs(names: tuple[str, ...]) -> None:
    assert [name for name in names if not hasattr(Project, name)] == []


@pytest.mark.parametrize("names", REMOVED_VERBS)
def test_removed_verbs(names: tuple[str, ...]) -> None:
    assert [name for name in names if hasattr(Project, name)] == []


def test_config_is_a_property() -> None:
    assert isinstance(Project.config, property)
    assert not hasattr(Project, "cfg")


SYNTHETIC = {"workflow": {"mode": "simulation"}, "geographic": {"source_mode": "synthetic"}}


def test_sealed_snapshot_root(tmp_path: Path) -> None:
    from hydromodpy.project.facade import read_sealed_config

    snapshot = {**SYNTHETIC, "workspace": {"project_root": str(tmp_path)}}

    cfg = read_sealed_config(snapshot)

    assert cfg.workspace.project_root == tmp_path.resolve()
    assert cfg.read_as_sealed is True


def test_status_plans(monkeypatch: pytest.MonkeyPatch) -> None:
    import hydromodpy.project.api as api

    seen: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(api, "status", lambda ref, **kwargs: seen.append((ref, kwargs)) or "report")
    project = SimpleNamespace()
    assert Project.status(project) == "report"
    assert seen == [(project, {"plan": True})]
