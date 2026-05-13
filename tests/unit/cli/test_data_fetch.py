"""Tests for ``hmp data fetch``."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


def _load_main():
    return importlib.import_module("hydromodpy.cli.main")


def _run(monkeypatch, argv: list[str]) -> int:
    """Run ``hmp`` and tolerate handlers that do not call sys.exit explicitly."""
    module = _load_main()
    monkeypatch.setattr(sys, "argv", argv)
    try:
        module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "projects").mkdir()
    (workspace / "data").mkdir()
    return workspace


def test_data_fetch_help_displays(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "data", "fetch", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "variable" in out
    assert "--bbox" in out


def test_data_fetch_dem_writes_sidecar(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_workspace(tmp_path)
    code = _run(
        monkeypatch,
        [
            "hmp",
            "data",
            "fetch",
            "dem",
            "--workspace",
            str(workspace),
            "--bbox",
            "0,0,1,1",
            "--source",
            "test",
        ],
    )
    assert code == 0

    raw_dir = workspace / "data" / "dem" / "raw"
    assert raw_dir.is_dir()

    tifs = list(raw_dir.glob("*.tif"))
    assert tifs, "no .tif written"
    sidecars = list(raw_dir.glob("*.tif.json"))
    assert sidecars, "no sidecar written"

    payload = json.loads(sidecars[0].read_text())
    assert payload["source"] == "test"
    assert payload["bbox"] == [0.0, 0.0, 1.0, 1.0]
    assert len(payload["sha256"]) == 64


def test_data_fetch_unknown_variable_fails(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_workspace(tmp_path)
    code = _run(
        monkeypatch,
        ["hmp", "data", "fetch", "not_a_var", "--workspace", str(workspace)],
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "Unknown variable" in err


def test_data_fetch_invalid_bbox_fails(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_workspace(tmp_path)
    code = _run(
        monkeypatch,
        [
            "hmp",
            "data",
            "fetch",
            "dem",
            "--workspace",
            str(workspace),
            "--bbox",
            "not-floats",
        ],
    )
    assert code == 1
