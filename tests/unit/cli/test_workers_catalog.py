"""Tests for ``hydromodpy.cli._workers.catalog`` helpers."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import duckdb
import pandas as pd
import pytest

import hydromodpy as hmp
from hydromodpy.cli._workers.catalog import (
    list_simulations,
    query_catalog,
    rename_simulation,
    show_simulation,
    trash_simulation,
)
from hydromodpy.results.catalog.registration import DuplicateSimulationNameError


def _seed_workspace(tmp_path: Path) -> tuple[Path, str]:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "data").mkdir()
    project_dir = workspace / "projects" / "demo"
    project_dir.mkdir(parents=True)

    sim_id = str(uuid4())
    with hmp.open(project_dir, create=True) as catalog:
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


def _seed_project(tmp_path: Path) -> tuple[Path, str]:
    project_dir = tmp_path / "ws" / "projects" / "demo"
    project_dir.mkdir(parents=True)
    sim_id = str(uuid4())
    with hmp.open(project_dir, create=True) as catalog:
        catalog.register_simulation(
            sim_id=sim_id,
            project="demo",
            solver="modflow_nwt",
            name="baseline",
            flow_regime="steady",
            n_cells=4,
            n_layers=1,
        )
        catalog.finalize(sim_id, status="completed", duration_s=0.5)
    return project_dir, sim_id


def _seed_project_catalog(tmp_path: Path) -> Path:
    project_dir = tmp_path / "ws" / "projects" / "demo"
    project_dir.mkdir(parents=True)
    with hmp.open(project_dir, create=True):
        pass
    return project_dir


def test_list_simulations_returns_dataframe(tmp_path: Path) -> None:
    workspace, sim_id = _seed_workspace(tmp_path)
    df = list_simulations(workspace)
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert sim_id in df["sim_id"].astype(str).tolist()
    assert "demo" in df["project"].tolist()


def test_list_simulations_filters_by_solver(tmp_path: Path) -> None:
    workspace, _ = _seed_workspace(tmp_path)
    df = list_simulations(workspace, solver="nwt")
    assert not df.empty
    assert (df["solver"].str.contains("nwt")).all()


def test_list_simulations_empty_workspace_returns_empty_frame(tmp_path: Path) -> None:
    workspace = tmp_path / "empty"
    workspace.mkdir()
    df = list_simulations(workspace)
    assert df.empty


def test_list_simulations_limit(tmp_path: Path) -> None:
    workspace, _ = _seed_workspace(tmp_path)
    df = list_simulations(workspace, limit=1)
    assert len(df) <= 1


def test_show_simulation_returns_metadata(tmp_path: Path) -> None:
    project_dir, sim_id = _seed_project(tmp_path)
    payload = show_simulation(sim_id, workspace=project_dir)
    assert payload["sim_id"] == sim_id
    assert payload["name"] == "baseline"
    assert payload["solver"] == "modflow_nwt"
    assert payload["status"] == "completed"


def test_show_simulation_detail_adds_zarr_info(tmp_path: Path) -> None:
    project_dir, sim_id = _seed_project(tmp_path)
    payload = show_simulation(sim_id, workspace=project_dir, detail=True)
    assert "zarr_path" in payload
    assert "zarr_exists" in payload
    assert "zarr_groups" in payload


def test_show_simulation_missing_catalog_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        show_simulation("deadbeef", workspace=empty)


def test_query_catalog_returns_dataframe(tmp_path: Path) -> None:
    project_dir = _seed_project_catalog(tmp_path)
    df = query_catalog("SELECT 42 AS answer", workspace=project_dir)
    assert df.iloc[0]["answer"] == 42


def test_query_catalog_missing_catalog_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        query_catalog("SELECT 1", workspace=empty)


def test_query_catalog_invalid_sql_raises_duckdb_error(tmp_path: Path) -> None:
    project_dir = _seed_project_catalog(tmp_path)
    with pytest.raises(duckdb.Error):
        query_catalog("THIS IS NOT SQL", workspace=project_dir)


def test_query_catalog_limit_clause(tmp_path: Path) -> None:
    project_dir = _seed_project_catalog(tmp_path)
    df = query_catalog(
        "SELECT 1 AS x UNION SELECT 2 UNION SELECT 3", workspace=project_dir, limit=2
    )
    assert len(df) == 2


def _seed_named(project_dir: Path, name: str) -> str:
    sim_id = str(uuid4())
    with hmp.open(project_dir, create=True) as catalog:
        catalog.register_simulation(sim_id=sim_id, project="demo", solver="modflow6", name=name)
        catalog.finalize(sim_id, status="completed", duration_s=0.1)
    return sim_id


# ---------------------------------------------------------------------------
# rename worker
# ---------------------------------------------------------------------------


def test_rename_worker_happy_path(tmp_path: Path) -> None:
    project_dir, sim_id = _seed_project(tmp_path)
    result = rename_simulation(sim_id, workspace=project_dir, new_name="renamed")
    assert result == {"sim_id": sim_id, "name": "renamed"}
    with hmp.open(project_dir) as catalog:
        assert catalog[sim_id].name == "renamed"


def test_rename_worker_collision_raises(tmp_path: Path) -> None:
    project_dir, first = _seed_project(tmp_path)  # name 'baseline'
    second = _seed_named(project_dir, "other")
    with pytest.raises(DuplicateSimulationNameError):
        rename_simulation(second, workspace=project_dir, new_name="baseline")


def test_rename_worker_prefix_ref(tmp_path: Path) -> None:
    project_dir, sim_id = _seed_project(tmp_path)
    prefix = sim_id.replace("-", "")[:8]
    result = rename_simulation(prefix, workspace=project_dir, new_name="by_prefix")
    assert result["sim_id"] == sim_id
    assert result["name"] == "by_prefix"


def test_rename_worker_trashed_sim(tmp_path: Path) -> None:
    project_dir, sim_id = _seed_project(tmp_path)
    trash_simulation(sim_id, workspace=project_dir)
    # A trashed run has name NULL; it resolves by id and rename still applies.
    result = rename_simulation(sim_id, workspace=project_dir, new_name="revived")
    assert result["sim_id"] == sim_id
    with hmp.open(project_dir) as catalog:
        assert catalog[sim_id].name == "revived"
