"""Tests for ``hmp index``."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest


def _load_main():
    return importlib.import_module("hydromodpy.cli.main")


def _run(monkeypatch, argv: list[str]) -> int:
    module = _load_main()
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc_info:
        module.main()
    return int(exc_info.value.code or 0)


@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    """Redirect HMP_STATE_HOME so the global index lives in tmp_path."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setenv("HMP_STATE_HOME", str(state_dir))
    yield state_dir


def test_index_help_displays(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "index", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "search" in out
    assert "forget" in out
    assert "prune" in out


def test_index_search_help_displays(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "index", "search", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "term" in out


def test_index_search_empty_returns_zero(monkeypatch, capsys, isolated_state) -> None:
    code = _run(monkeypatch, ["hmp", "index", "search", "anything"])
    assert code == 0
    out = capsys.readouterr().out
    assert "No matches" in out


def test_index_prune_empty_returns_zero(monkeypatch, capsys, isolated_state) -> None:
    code = _run(monkeypatch, ["hmp", "index", "prune"])
    assert code == 0
    out = capsys.readouterr().out
    assert "No stale" in out or "Pruned" in out


def test_index_forget_unknown_returns_zero(monkeypatch, capsys, isolated_state) -> None:
    code = _run(monkeypatch, ["hmp", "index", "forget", "nonexistent-id"])
    # forget silently no-ops when the row is absent
    assert code == 0
    out = capsys.readouterr().out
    assert "nonexistent-id" in out
