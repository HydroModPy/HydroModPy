"""The ``hmp catalog`` reading workers answer from the index of an indexed project."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from hydromodpy.cli._workers.catalog import (
    diff_simulations,
    list_simulations,
    query_catalog,
    show_simulation,
)
from hydromodpy.core.state.layout import PROJECTS_DIRNAME, WORKSPACE_TOML_FILENAME
from hydromodpy.results.catalog import rebuild_index
from tests._helpers.sealed_runs import make_project, seal_run


def _seed_workspace(tmp_path: Path) -> tuple[Path, Path, str]:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / WORKSPACE_TOML_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    project_dir = make_project(workspace / PROJECTS_DIRNAME / "demo")
    sim_id = seal_run(project_dir, "baseline", solver="modflow_nwt", nse=0.6, tags=("pinned",))
    seal_run(project_dir, "variant", solver="modflow6", nse=0.8, parameters={"K": 3e-5})
    rebuild_index(project_dir)
    return workspace, project_dir, sim_id


def test_list_simulations_returns_one_row_per_sealed_run(tmp_path: Path) -> None:
    workspace, _project, sim_id = _seed_workspace(tmp_path)

    df = list_simulations(workspace)

    assert isinstance(df, pd.DataFrame)
    assert sim_id in df["sim_id"].tolist()
    assert set(df["name"]) == {"baseline", "variant"}
    assert set(df["project"]) == {"demo"}
    assert {"site", "case_id", "rel_dir", "label", "nse"} <= set(df.columns)


def test_list_simulations_filters(tmp_path: Path) -> None:
    workspace, _project, _sim_id = _seed_workspace(tmp_path)

    assert list_simulations(workspace, solver="nwt")["name"].tolist() == ["baseline"]
    assert list_simulations(workspace, tag="pinned")["name"].tolist() == ["baseline"]
    assert list_simulations(workspace, label="exploratory").shape[0] == 2
    assert list_simulations(workspace, site="nowhere").empty
    assert list_simulations(workspace, limit=1).shape[0] == 1


def test_the_solver_filter_matches_a_run_that_stored_a_solver_list(tmp_path: Path) -> None:
    workspace, project, _sim_id = _seed_workspace(tmp_path)
    seal_run(project, "chain", solver="modflow6,modpath", nse=0.7)
    rebuild_index(project)

    assert set(list_simulations(workspace, solver="modflow6")["name"]) == {"variant", "chain"}


def test_list_simulations_without_an_index_is_empty(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "data").mkdir()

    assert list_simulations(workspace).empty


def test_show_simulation_returns_the_facts(tmp_path: Path) -> None:
    _workspace, project, sim_id = _seed_workspace(tmp_path)

    payload = show_simulation("baseline", workspace=project)

    assert payload["sim_id"] == sim_id
    assert payload["rel_dir"] == "runs/baseline"
    assert payload["label"] == "exploratory"
    assert payload["nse"] == 0.6
    assert payload["exports"] == []


def test_show_simulation_detail_adds_the_zarr_layout(tmp_path: Path) -> None:
    _workspace, project, _sim_id = _seed_workspace(tmp_path)

    payload = show_simulation("variant", workspace=project, detail=True)

    assert "zarr_path" in payload
    assert payload["zarr_exists"] is False


def test_show_simulation_without_an_index_raises(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")

    with pytest.raises(FileNotFoundError, match="reindex"):
        show_simulation("baseline", workspace=project)


def test_query_catalog_reads_the_views(tmp_path: Path) -> None:
    _workspace, project, _sim_id = _seed_workspace(tmp_path)

    df = query_catalog("SELECT name, label FROM v_cases ORDER BY name", workspace=project)

    assert df["name"].tolist() == ["baseline", "variant"]
    assert query_catalog("SELECT name FROM simulations", workspace=project, limit=1).shape[0] == 1


def test_query_catalog_invalid_sql_raises_duckdb_error(tmp_path: Path) -> None:
    _workspace, project, _sim_id = _seed_workspace(tmp_path)

    with pytest.raises(duckdb.Error):
        query_catalog("SELECT * FROM no_such_table", workspace=project)


def test_diff_simulations_compares_parameters(tmp_path: Path) -> None:
    _workspace, project, _sim_id = _seed_workspace(tmp_path)

    delta = diff_simulations("baseline", "variant", workspace=project)

    assert ("K", "catchment") in delta["params"]
