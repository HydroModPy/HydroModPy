"""``hmp project array`` writes the SLURM job of the current plan and says how to submit it.

The action is driven through its own parser, the way the ``hmp project``
family registers it; errors leave through the typed exit codes.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from hydromodpy.cli.commands.campaign import array
from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_USAGE
from tests.unit.project.test_slurm_array import planned_project


def _invoke(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="hmp project")
    array.register(parser.add_subparsers())
    try:
        args = parser.parse_args([array.NAME, *argv])
        args._handler(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_the_action_writes_the_job_and_prints_the_submission(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "p"
    planned_project(root, threads=2)

    code = _invoke([str(root), "--scheduler", "slurm", "--partition", "normal"])

    assert code == 0
    jobs = list((root / "jobs").iterdir())
    assert len(jobs) == 1 and jobs[0].name.endswith("-slurm")
    assert {"prepare.sh", "array.sh", "cases.txt"} <= {p.name for p in jobs[0].iterdir()}
    out = capsys.readouterr().out
    assert f"sbatch --parsable {jobs[0] / 'prepare.sh'}" in out
    assert f"sbatch --dependency=afterok:$prep {jobs[0] / 'array.sh'}" in out
    assert "3 case(s)" in out and "Not verified on a cluster" in out


def test_the_project_file_names_its_project(tmp_path: Path) -> None:
    root = tmp_path / "p"
    planned_project(root)

    assert _invoke([str(root / "project.toml"), "--scheduler", "slurm"]) == 0
    assert (root / "jobs").is_dir()


def test_the_scheduler_is_required(tmp_path: Path) -> None:
    root = tmp_path / "p"
    planned_project(root)

    assert _invoke([str(root)]) == EXIT_USAGE
    assert _invoke([str(root), "--scheduler", "pbs"]) == EXIT_USAGE
    assert not (root / "jobs").exists()


def test_errors_leave_through_typed_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unplanned = tmp_path / "unplanned"
    unplanned.mkdir()
    assert _invoke([str(unplanned), "--scheduler", "slurm"]) == EXIT_NOT_FOUND
    assert "no plan" in capsys.readouterr().err

    root = tmp_path / "p"
    planned_project(root)
    assert _invoke([str(root), "--scheduler", "slurm", "--time", "5"]) == EXIT_CONFIG
    assert "walltime" in capsys.readouterr().err
