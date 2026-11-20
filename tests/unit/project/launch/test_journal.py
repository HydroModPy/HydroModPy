"""The journal of a launch: ``jobs/<stamp>-<scheduler>/`` and its case list.

A task of a job names the case file of its line in ``cases.txt``, whatever the
plan that is current later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.project.launch.journal import (
    CASES_FILENAME,
    case_for_task,
    new_job_dir,
    write_case_list,
)
from hydromodpy.project.launch.slurm import write_slurm_array
from tests.unit.project.launch._helpers import STAMP, planned_project


def test_a_task_of_a_job_names_its_case_file(tmp_path: Path) -> None:
    project = tmp_path / "campaign"
    project.mkdir()
    (project / "project.toml").write_text("", encoding="utf-8")
    job = new_job_dir(project, "slurm")
    write_case_list(job, ["plan/abc/alpha-base.toml", "plan/abc/beta-base.toml"])

    assert (job / CASES_FILENAME).is_file()
    assert case_for_task(project, job.name, 2) == project.resolve() / "plan/abc/beta-base.toml"
    with pytest.raises(IndexError, match="1..2"):
        case_for_task(project, job.name, 3)


def test_hmp_project_case_reads_the_line_of_its_task(tmp_path: Path) -> None:
    root = tmp_path / "p"
    stored = planned_project(root)
    job = write_slurm_array(root, stamp=STAMP)

    first = case_for_task(root, f"{STAMP}-slurm", 1)
    last = case_for_task(root, job.directory, 3)

    assert first == stored.directory / "J001-base.toml"
    assert last == stored.directory / "J003-calage.toml"
    for task in (0, 4):
        with pytest.raises(IndexError, match="1..3"):
            case_for_task(root, job.directory.name, task)
