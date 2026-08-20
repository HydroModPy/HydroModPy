"""Tests for ``hmp workspace`` global-index actions (register/search/forget/prune).

The registry is project-scoped: one row per project root. A workspace root is
accepted as a shortcut and expands to the projects it holds, so the two never
land as equivalent rows. Only a path that is not on disk is refused.

An empty result therefore has two readings the command must keep apart: a
workspace that holds no project yet registered nothing because there was
nothing to register, while a workspace whose projects are all known registered
nothing because the work was already done.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import duckdb
import pytest


def _load_main():
    return importlib.import_module("hydromodpy.cli.main")


def _run(monkeypatch, argv: list[str]) -> int:
    module = _load_main()
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc_info:
        module.main()
    return int(exc_info.value.code or 0)


def _seed_project_with_catalog(project_root: Path) -> None:
    """Create a project root with an empty v2 catalog so ``register`` accepts it."""
    from hydromodpy.core.state.paths import catalog_path_for

    catalog_path = catalog_path_for(project_root)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(catalog_path))
    try:
        conn.execute(
            "CREATE TABLE simulations ("
            "sim_id VARCHAR PRIMARY KEY, "
            "description VARCHAR, "
            "solver VARCHAR)"
        )
    finally:
        conn.close()


def _seed_workspace(workspace_root: Path, *, projects: tuple[str, ...]) -> list[Path]:
    """Create a workspace root holding ``projects``, each with its own catalog."""
    from hydromodpy.core.state.paths import PROJECTS_DIRNAME, WORKSPACE_TOML_FILENAME

    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / WORKSPACE_TOML_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    (workspace_root / PROJECTS_DIRNAME).mkdir(exist_ok=True)
    roots: list[Path] = []
    for name in projects:
        project_root = workspace_root / PROJECTS_DIRNAME / name
        project_root.mkdir(parents=True, exist_ok=True)
        _seed_project_with_catalog(project_root)
        roots.append(project_root)
    return roots


@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    """Redirect HMP_STATE_HOME so the global index lives in tmp_path."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setenv("HMP_STATE_HOME", str(state_dir))
    yield state_dir


def test_index_help_displays(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "workspace", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "search" in out
    assert "forget" in out
    assert "prune" in out
    assert "register" in out


def test_index_help_says_it_registers_projects(monkeypatch, capsys) -> None:
    """The family help must not promise a workspace-level registry."""
    code = _run(monkeypatch, ["hmp", "workspace", "--help"])
    assert code == 0
    out = " ".join(capsys.readouterr().out.lower().split())
    assert "list the projects registered in the machine-wide global index" in out
    assert "register a project in the global index" in out
    assert "workspaces registered" not in out


def test_index_search_help_displays(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "workspace", "search", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "term" in out


def test_index_search_empty_returns_zero(monkeypatch, capsys, isolated_state) -> None:
    code = _run(monkeypatch, ["hmp", "workspace", "search", "anything"])
    assert code == 0
    out = capsys.readouterr().out
    assert "No matches" in out


def test_index_prune_empty_returns_zero(monkeypatch, capsys, isolated_state) -> None:
    code = _run(monkeypatch, ["hmp", "workspace", "prune"])
    assert code == 0
    out = capsys.readouterr().out
    assert "No stale" in out or "Pruned" in out


def test_index_forget_unknown_returns_zero(monkeypatch, capsys, isolated_state) -> None:
    code = _run(monkeypatch, ["hmp", "workspace", "forget", "nonexistent-id"])
    # forget silently no-ops when the row is absent
    assert code == 0
    out = capsys.readouterr().out
    assert "nonexistent-id" in out


def test_register_project_via_cli(monkeypatch, capsys, tmp_path, isolated_state) -> None:
    """``hmp workspace register`` prints the assigned project_id and persists it."""
    project = tmp_path / "cheze"
    _seed_project_with_catalog(project)

    code = _run(monkeypatch, ["hmp", "workspace", "register", str(project), "--label", "alpha"])
    assert code == 0
    project_id = capsys.readouterr().out.strip()
    assert project_id
    # The project_id must be a UUID-ish identifier (no spaces or punctuation lines).
    assert "\n" not in project_id

    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex() as gi:
        records = gi.list_projects()
    assert len(records) == 1
    assert records[0].project_id == project_id
    assert records[0].label == "alpha"
    assert records[0].project_uri == str(project.resolve())


def test_register_workspace_via_cli_expands_to_projects(
    monkeypatch, capsys, tmp_path, isolated_state
) -> None:
    """A workspace root registers its projects, never itself."""
    workspace = tmp_path / "ws"
    alpha, beta = _seed_workspace(workspace, projects=("alpha", "beta"))

    code = _run(monkeypatch, ["hmp", "workspace", "register", str(workspace)])
    assert code == 0
    printed = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(printed) == 2

    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex() as gi:
        uris = {record.project_uri for record in gi.list_projects()}
    assert uris == {str(alpha.resolve()), str(beta.resolve())}
    assert str(workspace.resolve()) not in uris


def test_register_a_missing_root_exits_not_found(
    monkeypatch, capsys, tmp_path, isolated_state
) -> None:
    """A path that is not on disk is the one register refuses."""
    missing = tmp_path / "typo"
    code = _run(monkeypatch, ["hmp", "workspace", "register", str(missing)])
    assert code == 10
    assert "typo" in capsys.readouterr().err


def test_register_a_project_root_without_catalog_succeeds(
    monkeypatch, capsys, tmp_path, isolated_state
) -> None:
    """A project registered before its first run is the normal case, not an error."""
    project = tmp_path / "brand_new"
    project.mkdir()

    code = _run(monkeypatch, ["hmp", "workspace", "register", str(project)])
    assert code == 0
    printed = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(printed) == 1

    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex() as gi:
        assert [r.project_uri for r in gi.list_projects()] == [str(project.resolve())]


def test_register_an_empty_workspace_says_nothing_was_there(
    monkeypatch, capsys, tmp_path, isolated_state
) -> None:
    """A freshly scaffolded workspace registered nothing because it holds nothing."""
    workspace = tmp_path / "ws_empty"
    _seed_workspace(workspace, projects=())

    code = _run(monkeypatch, ["hmp", "workspace", "register", str(workspace)])
    assert code == 0
    out = capsys.readouterr().out
    assert "No project" in out
    assert "already registered" not in out


def test_register_twice_says_the_projects_were_already_registered(
    monkeypatch, capsys, tmp_path, isolated_state
) -> None:
    """The same empty result, the opposite reason: the command must not conflate them."""
    workspace = tmp_path / "ws"
    _seed_workspace(workspace, projects=("alpha", "beta"))
    assert _run(monkeypatch, ["hmp", "workspace", "register", str(workspace)]) == 0
    capsys.readouterr()

    code = _run(monkeypatch, ["hmp", "workspace", "register", str(workspace)])
    assert code == 0
    out = capsys.readouterr().out
    assert "2 project(s)" in out
    assert "are registered" in out


def test_register_help_mentions_root_uri(monkeypatch, capsys) -> None:
    """``hmp workspace register --help`` documents the root_uri arg."""
    code = _run(monkeypatch, ["hmp", "workspace", "register", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "root_uri" in out
    assert "--label" in out


def test_index_list_empty_returns_zero(monkeypatch, capsys, isolated_state) -> None:
    """``hmp workspace list`` on an empty index says so instead of crashing."""
    code = _run(monkeypatch, ["hmp", "workspace", "list"])
    assert code == 0
    assert "no registered projects" in capsys.readouterr().out


def test_index_list_renders_registered_rows(monkeypatch, capsys, tmp_path, isolated_state) -> None:
    """``hmp workspace list`` renders a table of the registered projects."""
    project = tmp_path / "listed"
    _seed_project_with_catalog(project)
    assert (
        _run(monkeypatch, ["hmp", "workspace", "register", str(project), "--label", "listed"]) == 0
    )
    capsys.readouterr()

    code = _run(monkeypatch, ["hmp", "workspace", "list"])
    assert code == 0
    out = capsys.readouterr().out
    assert "project_id" in out
    assert "project_uri" in out
    assert "listed" in out
    assert str(project.resolve()) in out


def test_index_list_json_emits_record_fields(monkeypatch, capsys, tmp_path, isolated_state) -> None:
    """``hmp workspace list --json`` emits one object per registered project."""
    import json

    project = tmp_path / "jsoned"
    _seed_project_with_catalog(project)
    assert (
        _run(monkeypatch, ["hmp", "workspace", "register", str(project), "--label", "jsoned"]) == 0
    )
    capsys.readouterr()

    code = _run(monkeypatch, ["hmp", "workspace", "list", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["label"] == "jsoned"
    assert payload[0]["project_uri"] == str(project.resolve())
    assert payload[0]["last_scanned_at"] is None
