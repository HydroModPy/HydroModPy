"""The runs of several projects are read from their ``simulation.parquet`` files, without any index."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.state.layout import PROJECTS_DIRNAME, WORKSPACE_TOML_FILENAME
from hydromodpy.results.catalog.federation import read_workspace_runs
from hydromodpy.results.storage.contract import TABLES_DIRNAME
from tests._helpers.sealed_runs import make_project, seal_run


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


def test_a_project_root_reads_its_own_runs_and_its_kept_trials(tmp_path):
    _ws, alpha, _beta = _seed_workspace(tmp_path)
    seal_run(alpha, "a_t1", rel_dir="sessions/calage/trials/0001", project="alpha")

    frame = read_workspace_runs(alpha)

    assert sorted(frame["rel_dir"]) == ["runs/a1", "runs/a2", "sessions/calage/trials/0001"]


def test_a_seal_without_its_parquet_row_is_skipped(tmp_path):
    _ws, alpha, _beta = _seed_workspace(tmp_path)
    (alpha / "runs" / "a2" / TABLES_DIRNAME / "simulation.parquet").unlink()

    frame = read_workspace_runs([alpha])

    assert sorted(frame["name"]) == ["a1"]


def test_nothing_sealed_gives_an_empty_frame(tmp_path):
    root = make_project(tmp_path / "empty")

    assert read_workspace_runs(root).empty
