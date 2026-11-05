"""The runs of several projects are read from their ``simulation.parquet`` files, without any index."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.state.layout import PROJECTS_DIRNAME, WORKSPACE_TOML_FILENAME, catalog_path_for
from hydromodpy.results.catalog import read_workspace_runs
from hydromodpy.results.catalog.federation import PROJECT_ROOT_COLUMN, sealed_run_dirs
from hydromodpy.results.storage.contract import TABLES_DIRNAME
from tests._helpers.sealed_runs import make_project, seal_run, write_attempt


def _seed_workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / WORKSPACE_TOML_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    alpha = make_project(workspace / PROJECTS_DIRNAME / "alpha")
    beta = make_project(workspace / PROJECTS_DIRNAME / "beta")
    seal_run(alpha, "a1", project="alpha", nse=0.5)
    seal_run(alpha, "a2", project="alpha", nse=0.7)
    seal_run(beta, "b1", project="beta", site="J0014020", nse=0.9)
    return workspace, alpha, beta


def test_a_workspace_federates_the_sealed_runs_of_its_projects(tmp_path):
    workspace, alpha, beta = _seed_workspace(tmp_path)
    assert not catalog_path_for(alpha).exists() and not catalog_path_for(beta).exists()

    frame = read_workspace_runs(workspace)

    assert sorted(frame["name"]) == ["a1", "a2", "b1"]
    assert set(frame[PROJECT_ROOT_COLUMN]) == {str(alpha.resolve()), str(beta.resolve())}
    assert {"site", "case_id", "rel_dir", "nse"} <= set(frame.columns)
    assert "label" not in frame.columns
    assert frame.loc[frame["name"] == "b1", "site"].item() == "J0014020"


def test_a_project_root_reads_its_own_runs_and_its_kept_trials(tmp_path):
    _ws, alpha, _beta = _seed_workspace(tmp_path)
    seal_run(alpha, "a_t1", rel_dir="sessions/calage/trials/0001", project="alpha")

    frame = read_workspace_runs(alpha)

    assert sorted(frame["rel_dir"]) == ["runs/a1", "runs/a2", "sessions/calage/trials/0001"]


def test_an_attempt_without_a_seal_is_not_a_run(tmp_path):
    _ws, alpha, _beta = _seed_workspace(tmp_path)
    write_attempt(alpha, "runs/failed_one", status="failed")

    assert [p.name for p in sealed_run_dirs(alpha)] == ["a1", "a2"]


def test_a_seal_without_its_parquet_row_is_skipped(tmp_path):
    _ws, alpha, _beta = _seed_workspace(tmp_path)
    (alpha / "runs" / "a2" / TABLES_DIRNAME / "simulation.parquet").unlink()

    frame = read_workspace_runs([alpha])

    assert sorted(frame["name"]) == ["a1"]


def test_nothing_sealed_gives_an_empty_frame(tmp_path):
    root = make_project(tmp_path / "empty")

    assert read_workspace_runs(root).empty
