"""End-to-end: workspace init -> sealed run -> catalog ls / show / query.

Drives the catalog browsing surface (``hmp catalog ls``, ``hmp catalog show``,
``hmp catalog query``) against the index of a project, rebuilt from a run
sealed the way the pipeline seals one.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.cli_runner import CliRunner
from tests._helpers.run_stores import open_run_store


def _seed_project_with_simulation(workspace: Path, project: str = "demo") -> str:
    """Initialise a workspace + project + one sealed, indexed simulation."""
    runner = CliRunner()
    runner.invoke(["hmp", "workspace", "init", "--path", str(workspace)])
    runner.invoke(["hmp", "project", "new", project, "--workspace", str(workspace)])

    project_dir = workspace / "projects" / project
    store = open_run_store(
        project_dir,
        "baseline",
        solver="modflow_nwt",
        flow_regime="steady",
        n_cells=4,
        n_layers=1,
        create_zarr=False,
    )
    sim_id = store.sim_id
    store.write_timeseries(
        sim_id,
        station_id="P01",
        variable="head",
        ts=pd.Series([1.0, 1.1], index=pd.date_range("2026-01-01", periods=2)),
    )
    seal_completed(store)
    rebuild_index(project_dir)
    return sim_id


def test_catalog_ls_lists_seeded_simulation(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    sim_id = _seed_project_with_simulation(workspace)

    runner = CliRunner()
    result = runner.invoke(
        [
            "hmp",
            "catalog",
            "ls",
            "--workspace",
            str(workspace),
            "--project",
            "demo",
        ]
    )
    assert result.ok, result.stderr
    assert "baseline" in result.stdout
    assert sim_id[:8] in result.stdout


def test_catalog_show_resolves_sim_by_prefix(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    sim_id = _seed_project_with_simulation(workspace)
    project_dir = workspace / "projects" / "demo"

    runner = CliRunner()
    result = runner.invoke(
        [
            "hmp",
            "catalog",
            "show",
            sim_id[:8],
            "--workspace",
            str(project_dir),
        ]
    )
    assert result.ok, result.stderr
    assert sim_id in result.stdout
    assert "baseline" in result.stdout
    assert "modflow_nwt" in result.stdout


def test_catalog_query_runs_sql_against_catalog(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _seed_project_with_simulation(workspace)
    project_dir = workspace / "projects" / "demo"

    runner = CliRunner()
    result = runner.invoke(
        [
            "hmp",
            "catalog",
            "query",
            "SELECT name FROM simulations",
            "--workspace",
            str(project_dir),
        ]
    )
    assert result.ok, result.stderr
    assert "baseline" in result.stdout
