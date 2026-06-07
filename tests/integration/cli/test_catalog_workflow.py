"""End-to-end: workspace init -> register sim -> catalog ls / show / query.

Drives the catalog browsing surface (``hmp catalog ls``, ``hmp catalog show``,
``hmp catalog query``) against a real per-project DuckDB catalog seeded via
the public Python API.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pandas as pd

from tests._helpers.cli_runner import CliRunner


def _seed_project_with_simulation(workspace: Path, project: str = "demo") -> str:
    """Initialise a workspace + project + one finalised simulation."""
    import hydromodpy as hmp

    runner = CliRunner()
    runner.invoke(["hmp", "workspace", "init", "--path", str(workspace)])
    runner.invoke(["hmp", "project", "new", project, "--workspace", str(workspace)])

    project_dir = workspace / "projects" / project
    sim_id = str(uuid4())
    with hmp.open(project_dir, create=True) as catalog:
        catalog.register_simulation(
            sim_id=sim_id,
            project=project,
            solver="modflow_nwt",
            name="baseline",
            flow_regime="steady",
            n_cells=4,
            n_layers=1,
        )
        catalog.write_timeseries(
            sim_id,
            station_id="P01",
            variable="head",
            ts=pd.Series([1.0, 1.1], index=pd.date_range("2026-01-01", periods=2)),
        )
        catalog.finalize(sim_id, status="completed", duration_s=0.1)
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
