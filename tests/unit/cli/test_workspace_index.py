"""Tests for ``hmp workspace`` global-index actions (register/search/forget/prune)."""

from __future__ import annotations

import importlib
import os
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


def _seed_workspace_with_catalog(workspace: Path) -> None:
    """Create a workspace with an empty v2 catalog so ``register`` accepts it."""
    from hydromodpy.core.state.paths import catalog_path_for

    catalog_path = catalog_path_for(workspace)
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


def test_register_workspace_via_cli(monkeypatch, capsys, tmp_path, isolated_state) -> None:
    """``hmp index register`` prints the assigned workspace_id and persists it."""
    ws = tmp_path / "ws_a"
    _seed_workspace_with_catalog(ws)

    code = _run(monkeypatch, ["hmp", "workspace", "register", str(ws), "--label", "alpha"])
    assert code == 0
    workspace_id = capsys.readouterr().out.strip()
    assert workspace_id
    # The workspace_id must be a UUID-ish identifier (no spaces or punctuation lines).
    assert "\n" not in workspace_id

    from hydromodpy.core.state.global_index import GlobalIndex

    with GlobalIndex() as gi:
        records = gi.list_workspaces()
    assert len(records) == 1
    assert records[0].workspace_id == workspace_id
    assert records[0].label == "alpha"
    assert records[0].workspace_uri == str(ws)


def test_register_missing_catalog_exits_not_found(
    monkeypatch, capsys, tmp_path, isolated_state
) -> None:
    """Registering a path without ``.hmp/index.duckdb`` returns EXIT_NOT_FOUND."""
    from hydromodpy.core.state.paths import CATALOG_FILENAME

    ws = tmp_path / "empty_ws"
    ws.mkdir()
    code = _run(monkeypatch, ["hmp", "workspace", "register", str(ws)])
    assert code == 10
    err = capsys.readouterr().err
    assert CATALOG_FILENAME in err


def test_register_help_mentions_workspace_uri(monkeypatch, capsys) -> None:
    """``hmp index register --help`` documents the workspace_uri arg."""
    code = _run(monkeypatch, ["hmp", "workspace", "register", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "workspace_uri" in out
    assert "--label" in out


def test_index_list_empty_returns_zero(monkeypatch, capsys, isolated_state) -> None:
    """``hmp workspace list`` on an empty index says so instead of crashing."""
    code = _run(monkeypatch, ["hmp", "workspace", "list"])
    assert code == 0
    assert "no registered workspaces" in capsys.readouterr().out


def test_index_list_renders_registered_rows(monkeypatch, capsys, tmp_path, isolated_state) -> None:
    """``hmp workspace list`` renders a table of the registered workspaces."""
    ws = tmp_path / "ws_listed"
    _seed_workspace_with_catalog(ws)
    assert _run(monkeypatch, ["hmp", "workspace", "register", str(ws), "--label", "listed"]) == 0
    capsys.readouterr()

    code = _run(monkeypatch, ["hmp", "workspace", "list"])
    assert code == 0
    out = capsys.readouterr().out
    assert "workspace_id" in out
    assert "workspace_uri" in out
    assert "listed" in out
    assert str(ws) in out


def test_index_list_json_emits_record_fields(monkeypatch, capsys, tmp_path, isolated_state) -> None:
    """``hmp workspace list --json`` emits one object per registered workspace."""
    import json

    ws = tmp_path / "ws_json"
    _seed_workspace_with_catalog(ws)
    assert _run(monkeypatch, ["hmp", "workspace", "register", str(ws), "--label", "jsoned"]) == 0
    capsys.readouterr()

    code = _run(monkeypatch, ["hmp", "workspace", "list", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["label"] == "jsoned"
    assert payload[0]["workspace_uri"] == str(ws)
    assert payload[0]["last_scanned_at"] is None
