"""Tests for :func:`hydromodpy.list_simulations`."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pandas as pd

import hydromodpy as hmp


def _seed_workspace(tmp_path: Path) -> tuple[Path, str]:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "data").mkdir()
    project_dir = workspace / "projects" / "demo"
    project_dir.mkdir(parents=True)
    (project_dir / "simulations").mkdir()

    sim_id = str(uuid4())
    with hmp.open(project_dir) as catalog:
        catalog.register_simulation(
            sim_id=sim_id,
            project="demo",
            solver="modflow_nwt",
            name="baseline",
            flow_regime="steady",
            n_cells=4,
            n_layers=1,
        )
        catalog.finalize(sim_id, status="completed", duration_s=0.1)
    return workspace, sim_id


def test_list_simulations_returns_dataframe(tmp_path: Path) -> None:
    workspace, sim_id = _seed_workspace(tmp_path)
    df = hmp.list_simulations(workspace)
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert sim_id in df["sim_id"].astype(str).tolist()
    assert "demo" in df["project"].tolist()


def test_list_simulations_filters_by_solver(tmp_path: Path) -> None:
    workspace, _ = _seed_workspace(tmp_path)
    df = hmp.list_simulations(workspace, solver="nwt")
    assert not df.empty
    assert (df["solver"].str.contains("nwt")).all()


def test_list_simulations_empty_workspace_returns_empty_frame(tmp_path: Path) -> None:
    workspace = tmp_path / "empty"
    workspace.mkdir()
    df = hmp.list_simulations(workspace)
    assert df.empty


def test_list_simulations_limit(tmp_path: Path) -> None:
    workspace, _ = _seed_workspace(tmp_path)
    df = hmp.list_simulations(workspace, limit=1)
    assert len(df) <= 1
