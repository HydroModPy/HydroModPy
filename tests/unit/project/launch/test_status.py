"""Where each case of the current plan stands, read from the disk alone.

A failed case is named once, a plan whose project files changed says ``stale``,
and a running task the scheduler says ended reads ``failed``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.core.state.paths import runs_dir_for
from hydromodpy.project.launch import plan_project, project_status, read_journal, run_plan
from hydromodpy.results.plan_store import read_plan
from tests.unit.project.launch._launch_fakes import (
    write_behaviour,
    write_project,
)

pytestmark = pytest.mark.allow_subprocess


def test_status_reads_the_disk_and_log_names_each_failed_case_once(
    tmp_path: Path, fake_worker: Path
) -> None:
    project = write_project(tmp_path)
    plan_project(project)
    planned = project_status(project)
    assert {row.status for row in planned.rows} == {"planned"}

    write_behaviour(project, {"beta-k2e_5": {"run": "fail"}})
    run_plan(project)
    status = {row.case_id: row for row in project_status(project).rows}

    assert status["beta-k2e_5"].status == "failed"
    assert status["beta-k2e_5"].error == "SolverError: boom"
    assert status["alpha-base"].status == "completed"
    assert status["alpha-base"].rel_dir == "runs/alpha-base"
    failed = read_journal(project, failed_only=True)
    assert [event["case_id"] for event in failed] == ["beta-k2e_5"]
    assert failed[0]["log_tail"] == ["boom"]


def test_status_says_stale_plan_once_the_project_files_change(
    tmp_path: Path, fake_worker: Path
) -> None:
    project = write_project(tmp_path)
    plan_project(project)
    sites = project / "sites.csv"
    sites.write_text(sites.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    report = project_status(project)

    assert report.plan_stale
    assert {row.status for row in report.rows} == {"stale_plan"}


def test_a_running_task_the_scheduler_says_ended_is_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hydromodpy.project.launch import sacct

    project = write_project(tmp_path)
    plan_project(project)
    case_id = read_plan(project).cases[0].case_id
    run_dir = runs_dir_for(project) / case_id
    run_dir.mkdir(parents=True)
    (run_dir / "outcome.json").write_text(
        json.dumps(
            {
                "schema": "hydromodpy.outcome.v1",
                "case_id": case_id,
                "attempt": 1,
                "attempt_id": "a1",
                "status": "running",
                "written_by": "worker",
                "started_at": datetime.now(UTC).isoformat(),
                "host": "node-12",
                "pid": os.getpid(),
                "scheduler_job_id": "80_1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sacct,
        "scheduler_states",
        lambda root: {case_id: sacct.SchedulerState(case_id, "80_1", "OUT_OF_MEMORY", "0:125")},
    )

    status = {row.case_id: row.status for row in project_status(project).rows}

    assert status[case_id] == "failed"
