"""``hmp publish .``: every sealed run and the summary, written all at once or not at all."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.cli.helpers import EXIT_OK
from hydromodpy.results.publication import read_published
from tests._helpers.cli_runner import CliRunner
from tests.unit.results._published_run import (
    RUN_NAME,
    make_project,
    make_sealed_run,
    make_summary,
)


def _invoke(*args: str):
    return CliRunner().invoke(["publish", *args])


def test_the_project_is_published_with_its_summary(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    make_sealed_run(project)
    make_summary(project, error_message=f"See {project}/runs/a/mfsim.lst for diagnostics")
    destination = tmp_path / "out"

    result = _invoke(".", "--to", str(destination), "-w", str(project))

    assert result.exit_code == EXIT_OK, result.stderr
    assert {entry.name for entry in destination.iterdir()} == {RUN_NAME, "summary"}
    assert "runs/a/mfsim.lst" in (destination / "summary" / "by_case.csv").read_text()
    assert "Published 2 copy(ies)" in result.stderr


def test_a_refused_summary_leaves_no_run_copy_behind(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    make_summary(project, error_message="ok", parquet_error=f"{project}/runs/a/mfsim.lst")
    destination = tmp_path / "out" / "bretagne"

    result = _invoke(".", "--to", str(destination), "-w", str(project))

    assert result.exit_code != EXIT_OK
    assert "Nothing was published" in result.stderr
    assert list((tmp_path / "out").iterdir()) == []
    assert read_published(run_dir) == []
