"""Auto-registration of projects in the global index on workflow setup.

The setup step must register the ``project_root`` in the machine-wide
:class:`GlobalIndex` so subsequent ``hmp workspace search`` calls federate
across every project that ever booted on the machine. One row is one project
root: the registry never holds a workspace root, since a workspace owns no
index database.

The fixtures here reproduce what the setup step really hands over: a project
root just created by ``Workspace``, carrying neither ``project.toml`` nor an
index database, because the run that writes them has not started. Marking the
directory first would only prove that the test agrees with the code.

Failures are best-effort: they must never raise. We assert silent recovery
when the index is unreachable (read-only state dir), idempotent behaviour on
duplicate registrations (``UNIQUE (project_uri)``), and that the hook obeys the
same admission rule as the manual ``register``, refusal of a path that does not
exist included.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.state.global_index import GlobalIndex, auto_register_projects
from hydromodpy.core.state.paths import (
    PROJECT_MARKER_FILENAME,
    PROJECTS_DIRNAME,
    WORKSPACE_TOML_FILENAME,
    scratch_dir_for,
)
from hydromodpy.core.state.run_state import WorkflowContext


class _DummyWorkspace:
    """Stand-in for the real ``Workspace``: it creates the directory, nothing else.

    No ``project.toml``, no ``.hmp/index.duckdb``. Both appear later, written
    by the run this setup step is preparing.
    """

    def __init__(self, config: object) -> None:
        self.config = config
        self.project_root = Path(getattr(config, "project_root", "workspace"))
        self.project_root.mkdir(parents=True, exist_ok=True)
        self.solver_scratch_folder = scratch_dir_for(self.project_root)
        self.catch_name = self.project_root.name


class _DummyGeographic:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def get_domain_surface_topo(self) -> SimpleNamespace:
        return SimpleNamespace(support=object())


def _noop_ensure(_state: object) -> None:
    """Replacement for ensure_flow / ensure_transport in tests."""


def _make_bare_project(project_root: Path) -> Path:
    """Create a project root the way the setup step does: an empty directory."""
    project_root.mkdir(parents=True, exist_ok=True)
    return project_root


def _make_marked_project(project_root: Path) -> Path:
    """Create a project root that already carries its ``project.toml``."""
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return project_root


def _make_workspace(workspace_root: Path, *, projects: tuple[str, ...] = ()) -> list[Path]:
    """Materialise a workspace root holding ``projects``."""
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / WORKSPACE_TOML_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    (workspace_root / PROJECTS_DIRNAME).mkdir(exist_ok=True)
    return [_make_marked_project(workspace_root / PROJECTS_DIRNAME / name) for name in projects]


def _patch_setup_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch heavyweight dependencies of ``run_setup`` for fast tests."""
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.Workspace", _DummyWorkspace)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.CatchmentDelineation",
        _DummyGeographic,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.Domain",
        lambda **kwargs: SimpleNamespace(**kwargs, zones={}),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.coerce_geographic_derived_features",
        lambda *, geographic: SimpleNamespace(
            surface_topo=SimpleNamespace(support=object()),
            to_domain_geographic_context=lambda: SimpleNamespace(),
        ),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.apply_catchment_zones_to_domain",
        lambda **kwargs: None,
    )
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.ensure_flow", _noop_ensure)
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.ensure_transport", _noop_ensure)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.resolve_dem_init_path",
        lambda cfg, run_state: None,
    )


def test_auto_register_projects_persists_uri(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A first call records the resolved project root exactly once."""
    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state"))

    project_root = _make_bare_project(tmp_path / "ws_a" / PROJECTS_DIRNAME / "demo")

    project_ids = auto_register_projects(project_root, label="demo")
    assert len(project_ids) == 1

    with GlobalIndex() as index:
        records = index.list_projects()

    assert len(records) == 1
    assert records[0].project_uri == str(project_root.resolve())
    assert records[0].label == "demo"


def test_auto_register_projects_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Duplicate registrations are silently absorbed by the UNIQUE constraint."""
    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state"))

    project_root = _make_bare_project(tmp_path / "cheze")

    first = auto_register_projects(project_root, label="cheze")
    second = auto_register_projects(project_root, label="cheze")

    assert len(first) == 1
    assert second == []

    with GlobalIndex() as index:
        records = index.list_projects()
    assert len(records) == 1
    assert records[0].project_id == first[0]


def test_auto_register_expands_a_workspace_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A workspace root and a project root must not land as equivalent rows."""
    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state"))

    workspace_root = tmp_path / "ws"
    alpha, beta = _make_workspace(workspace_root, projects=("alpha", "beta"))

    project_ids = auto_register_projects(workspace_root, label="ws")

    assert len(project_ids) == 2
    with GlobalIndex() as index:
        uris = {record.project_uri for record in index.list_projects()}
    assert uris == {str(alpha.resolve()), str(beta.resolve())}
    assert str(workspace_root.resolve()) not in uris


def test_auto_register_projects_skips_federation_refresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Auto-registration must not attach catalogs during concurrent runs."""
    from hydromodpy.core.state import global_index as gi_mod

    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state"))

    def _fail_refresh(_self: object) -> None:
        raise AssertionError("auto-registration should not refresh federation")

    monkeypatch.setattr(gi_mod.GlobalIndex, "refresh_federation", _fail_refresh)

    project_root = _make_bare_project(tmp_path / "no_refresh")

    project_ids = auto_register_projects(project_root, label="no-refresh")

    assert len(project_ids) == 1
    with GlobalIndex(refresh_federation=False) as index:
        records = index.list_projects()
    assert len(records) == 1
    assert records[0].project_id == project_ids[0]


def test_auto_register_projects_swallows_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Hook never raises: a broken index path is logged and returns an empty list."""
    from hydromodpy.core.state import global_index as gi_mod

    class _BrokenIndex:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("simulated index failure")

    monkeypatch.setattr(gi_mod, "GlobalIndex", _BrokenIndex)

    assert auto_register_projects(tmp_path / "broken") == []


def test_auto_register_projects_respects_env_opt_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Validation subprocesses can disable machine-wide index writes."""
    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HMP_AUTO_REGISTER_PROJECT", "0")

    project_root = _make_bare_project(tmp_path / "disabled")

    assert auto_register_projects(project_root, label="disabled") == []

    with GlobalIndex() as index:
        assert index.list_projects() == []


def test_auto_register_accepts_a_project_root_without_its_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The setup step registers before the run writes ``project.toml``.

    Requiring a marker here would silently drop the registration of every
    project on its first run, which is the whole reason the hook exists.
    """
    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state"))

    project_root = _make_bare_project(tmp_path / "brand_new")
    assert not (project_root / PROJECT_MARKER_FILENAME).exists()

    assert len(auto_register_projects(project_root, label="brand-new")) == 1

    with GlobalIndex() as index:
        assert [r.project_uri for r in index.list_projects()] == [str(project_root.resolve())]


def test_auto_register_reports_a_root_that_is_not_there(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A path that does not exist is a failed registration, said at WARNING."""
    import logging

    from hydromodpy.core.logging import get_logger

    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state"))

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    # The ``hydromodpy`` logger does not propagate, so caplog never sees it.
    parent = get_logger("hydromodpy")
    handler = _Capture(level=logging.WARNING)
    parent.addHandler(handler)
    try:
        assert auto_register_projects(tmp_path / "typo", label="typo") == []
    finally:
        parent.removeHandler(handler)

    warnings = [r.getMessage() for r in records if r.levelno >= logging.WARNING]
    assert any("typo" in message for message in warnings)
    with GlobalIndex() as index:
        assert index.list_projects() == []


def test_step_setup_registers_the_project_in_global_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """End-to-end: running the setup step adds the project root to the index."""
    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state"))
    _patch_setup_deps(monkeypatch)

    from hydromodpy.workflow.steps.setup import step_setup

    project_root = tmp_path / "ws_setup" / PROJECTS_DIRNAME / "demo"

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(project_root=project_root),
        geographic=SimpleNamespace(uses_synthetic_geographic=lambda: False),
        domain=SimpleNamespace(zone_ids=[]),
        simulation=SimpleNamespace(name="demo_run", run_id="test", rng_seed=None),
    )
    run_state = WorkflowContext(
        cfg=cfg,
        config_path=tmp_path / "config.toml",
        raw_toml={},
    )

    step_setup(run_state)

    with GlobalIndex() as index:
        uris = {record.project_uri for record in index.list_projects()}
    assert str(project_root.resolve()) in uris
