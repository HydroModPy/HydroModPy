"""Tests for ``hmp data export-package``."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest


def _load_main():
    return importlib.import_module("hydromodpy.cli.main")


def _run(monkeypatch, argv: list[str]) -> int:
    module = _load_main()
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc_info:
        module.main()
    return int(exc_info.value.code or 0)


def _register_minimal_simulation(workspace: Path, project: str = "demo") -> str:
    """Create a workspace with one finalised simulation. Returns the sim_id."""
    import hydromodpy as hmp

    sim_id = str(uuid4())
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    with hmp.open(workspace) as catalog:
        reg = catalog.register_simulation(
            sim_id=sim_id,
            project=project,
            solver="modflow_nwt",
            name="export-pkg-sim",
            flow_regime="steady",
            n_cells=4,
            n_layers=1,
        )
        sz = reg.zarr
        assert sz is not None
        sz.write_field(
            variable="head",
            timestep=0,
            values=np.full((1, 4), 1.0, dtype="float32"),
            n_timesteps=1,
        )
        catalog.write_timeseries(
            sim_id,
            station_id="P01",
            variable="head",
            ts=pd.Series([1.0, 1.1, 1.2], index=idx, name="head"),
        )
        catalog.finalize(sim_id, status="completed", duration_s=0.1)
    return sim_id


def test_export_package_help_displays(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "data", "export-package", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()
    assert "sim_ref" in out
    assert "--output" in out
    assert "--workspace" in out


def test_export_package_missing_workspace_errors(monkeypatch, tmp_path, capsys) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    code = _run(
        monkeypatch,
        [
            "hmp",
            "data",
            "export-package",
            "deadbeef-0000-0000-0000-000000000000",
            "-o",
            str(tmp_path / "out.hmp"),
            "-w",
            str(empty),
        ],
    )
    assert code != 0
    err = capsys.readouterr().err
    assert "No catalog found" in err


def test_export_package_writes_archive_to_output(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "ws"
    sim_id = _register_minimal_simulation(workspace)
    out_path = tmp_path / "exports" / "snap.hmp"

    code = _run(
        monkeypatch,
        [
            "hmp",
            "data",
            "export-package",
            sim_id,
            "-o",
            str(out_path),
            "-w",
            str(workspace),
        ],
    )
    assert code == 0
    assert out_path.is_file()
    assert out_path.stat().st_size > 0


def test_export_package_unknown_sim_returns_not_found(monkeypatch, tmp_path, capsys) -> None:
    workspace = tmp_path / "ws"
    _register_minimal_simulation(workspace)
    code = _run(
        monkeypatch,
        [
            "hmp",
            "data",
            "export-package",
            "00000000-0000-0000-0000-000000000099",
            "-o",
            str(tmp_path / "miss.hmp"),
            "-w",
            str(workspace),
        ],
    )
    assert code != 0
