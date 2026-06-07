"""Tests for ``hmp data get`` (formerly ``hmp data fetch``)."""

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
    code = _run(monkeypatch, ["hmp", "data", "get", "--help"])
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
            "get",
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

    var_dir = workspace / "data" / "dem"
    assert var_dir.is_dir()

    tifs = list(var_dir.glob("dem_*.tif"))
    assert tifs, "no .tif written"
    sidecars = list(var_dir.glob("dem_*.tif.json"))
    assert sidecars, "no sidecar written"

    payload = json.loads(sidecars[0].read_text())
    assert payload["source"] == "test"
    assert payload["bbox"] == [0.0, 0.0, 1.0, 1.0]
    assert len(payload["sha256"]) == 64


def test_data_fetch_unknown_variable_fails(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_workspace(tmp_path)
    code = _run(
        monkeypatch,
        ["hmp", "data", "get", "not_a_var", "--workspace", str(workspace)],
    )
    assert code == 14
    err = capsys.readouterr().err
    assert "Unknown variable" in err


def test_data_fetch_invalid_bbox_fails(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_workspace(tmp_path)
    code = _run(
        monkeypatch,
        [
            "hmp",
            "data",
            "get",
            "dem",
            "--workspace",
            str(workspace),
            "--bbox",
            "not-floats",
        ],
    )
    assert code != 0


def test_bbox_parses_negative_first_value(monkeypatch, tmp_path, capsys) -> None:
    """``--bbox=-1.17,48.4,-1.0,48.5`` parses without argparse swallowing the negative."""
    workspace = _make_workspace(tmp_path)
    code = _run(
        monkeypatch,
        [
            "hmp",
            "data",
            "get",
            "dem",
            "--workspace",
            str(workspace),
            "--bbox=-1.17,48.4,-1.0,48.5",
            "--source",
            "test",
        ],
    )
    assert code == 0
    sidecars = list((workspace / "data" / "dem").glob("dem_*.tif.json"))
    assert sidecars
    payload = json.loads(sidecars[0].read_text())
    assert payload["bbox"] == [-1.17, 48.4, -1.0, 48.5]


def test_bbox_help_mentions_equals_workaround(monkeypatch, capsys) -> None:
    """The help text steers users to ``--bbox=`` for negative minx values."""
    code = _run(monkeypatch, ["hmp", "data", "get", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    # argparse may wrap the literal --bbox=- mid-line; normalize whitespace.
    normalized = " ".join(out.split())
    assert "bbox=-" in normalized or "--bbox=-" in normalized


def test_bbox_three_values_fails(monkeypatch, tmp_path, capsys) -> None:
    """A bbox missing one coordinate is rejected."""
    workspace = _make_workspace(tmp_path)
    code = _run(
        monkeypatch,
        [
            "hmp",
            "data",
            "get",
            "dem",
            "--workspace",
            str(workspace),
            "--bbox",
            "0,1,2",
        ],
    )
    assert code != 0


def test_parse_bbox_helper_returns_tuple_of_floats() -> None:
    """The argparse type returns a 4-tuple of floats."""
    from hydromodpy.cli.commands.data.get import _parse_bbox

    parsed = _parse_bbox("-1.17,48.4,-1.0,48.5")
    assert parsed == (-1.17, 48.4, -1.0, 48.5)
    assert all(isinstance(x, float) for x in parsed)


def test_parse_bbox_helper_rejects_non_float() -> None:
    """The argparse type raises ``ArgumentTypeError`` on non-float."""
    import argparse as _argparse

    from hydromodpy.cli.commands.data.get import _parse_bbox

    with pytest.raises(_argparse.ArgumentTypeError):
        _parse_bbox("a,b,c,d")
