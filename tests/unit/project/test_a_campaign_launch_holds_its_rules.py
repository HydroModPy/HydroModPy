"""Rules a campaign launch keeps, measured on real launches of example 19.

Two cases of one site ask for the same data, so they are never prepared side
by side. A calibration case is done once one of its sessions holds the hash
of the plan, whatever the run it promoted seals. A case that never claimed a
directory says ``failed`` when the journal says so. A merge that fails fails
its case only. A launch that stops after the prepare phase solves nothing,
so the solve ceilings do not hold for it.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.core.state.paths import runs_dir_for, sessions_dir_for
from hydromodpy.project.launch import plan_project, project_status, run_plan
from hydromodpy.project.launch.children import PlannedCase
from hydromodpy.project.launch.local import select_cases
from hydromodpy.results.plan_store import read_plan
from hydromodpy.results.session.descriptor import SessionDescriptor, write_session
from tests._helpers.sealed_runs import manifest_document
from tests.unit.project._launch_fakes import seen, write_behaviour, write_project

pytestmark = pytest.mark.allow_subprocess


def _events(journal: Path, name: str) -> list[dict]:
    lines = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line["event"] == name]


def test_two_cases_of_one_site_are_never_prepared_side_by_side(
    tmp_path: Path, fake_worker: Path
) -> None:
    project = write_project(tmp_path, sites_extra="[sites.run]\nprepare_parallel = 4\n")
    write_behaviour(
        project,
        {case: {"prepare_sleep": 0.6} for case in ("alpha-base", "alpha-k2e_5", "beta-base")},
    )
    plan_project(project)

    run_plan(project, until="data")

    def window(case_id: str) -> tuple[float, float]:
        record = seen(project, case_id, "prepare")
        return record["started"], record["ended"]

    for site in ("alpha", "beta"):
        first, second = sorted([window(f"{site}-base"), window(f"{site}-k2e_5")])
        assert first[1] <= second[0], f"the two cases of {site} were prepared together"
    # Two sites still prepare side by side.
    alpha, beta = window("alpha-base"), window("beta-base")
    assert max(alpha[0], beta[0]) < min(alpha[1], beta[1])


def test_a_launch_until_data_names_the_cases_it_prepared_and_solves_nothing(
    tmp_path: Path, fake_worker: Path
) -> None:
    project = write_project(tmp_path)
    plan_project(project)

    # 50 solves would be refused for a launch that solves.
    report = run_plan(project, until="data", parallel=50)

    assert report.until == "data"
    assert sorted(report.prepared) == sorted(
        ["alpha-base", "alpha-k2e_5", "beta-base", "beta-k2e_5"]
    )
    assert report.cases == ()
    assert not runs_dir_for(project).exists()


def _write_session(project: Path, case_id: str, config_hash: str) -> None:
    now = datetime.now(UTC)
    write_session(
        sessions_dir_for(project) / case_id,
        SessionDescriptor(
            session_id="s1",
            case_id=case_id,
            config_hash=config_hash,
            hydromodpy_version="0",
            method="grid",
            objective_name="nse",
            status="completed",
            started_at=now,
            ended_at=now,
        ),
    )


def _promoted_run(project: Path, case_id: str, config_hash: str) -> None:
    run_dir = runs_dir_for(project) / case_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest_document(name=case_id, config_hash=config_hash)), encoding="utf-8"
    )


def _calibration_case(project: Path, case_id: str, config_hash: str) -> PlannedCase:
    return PlannedCase(
        case_id=case_id,
        site=case_id.split("-")[0],
        recipe=case_id.split("-")[1],
        config_hash=config_hash,
        path=project / "plan" / "abc" / f"{case_id}.toml",
        workflow="calibration",
        solves=1,
    )


def test_a_finished_calibration_is_not_started_again(tmp_path: Path) -> None:
    project = tmp_path / "campaign"
    case = _calibration_case(project, "nancon-calibration", "plan-hash")
    _write_session(project, case.case_id, "plan-hash")
    # The promoted run carries the K of the best trial: another hash.
    _promoted_run(project, case.case_id, "promoted-hash")

    chosen, _ = select_cases(project, [case])

    assert chosen == []


def test_a_calibration_whose_files_changed_is_started_again(tmp_path: Path) -> None:
    project = tmp_path / "campaign"
    case = _calibration_case(project, "nancon-calibration", "new-plan-hash")
    _write_session(project, case.case_id, "old-plan-hash")
    _promoted_run(project, case.case_id, "promoted-hash")

    chosen, _ = select_cases(project, [case])

    assert [planned.case_id for planned, _ in chosen] == ["nancon-calibration"]


def test_a_case_whose_prepare_failed_is_failed_and_leaves_no_scratch(
    tmp_path: Path, fake_worker: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The machine scratch of the shell must not move the folder this test watches.
    monkeypatch.delenv("HMP_SCRATCH_ROOT", raising=False)
    project = write_project(tmp_path)
    write_behaviour(project, {"alpha-base": {"prepare": "fail"}})
    plan_project(project)

    report = run_plan(project)

    status = {row.case_id: row.status for row in project_status(project).rows}
    assert status["alpha-base"] == "failed"
    assert status["beta-base"] == "completed"
    assert {case.case_id for case in report.cases if case.status == "failed"} == {"alpha-base"}
    scratch = project / ".hmp" / "scratch"
    assert not scratch.exists() or not list(scratch.glob("alpha-base.p*"))


def test_a_case_refused_before_its_claim_is_failed(tmp_path: Path, fake_worker: Path) -> None:
    project = write_project(tmp_path)
    write_behaviour(project, {"beta-k2e_5": {"run": "refuse"}})
    plan_project(project)

    run_plan(project)

    status = {row.case_id: row.status for row in project_status(project).rows}
    assert status["beta-k2e_5"] == "failed"
    assert status["alpha-base"] == "completed"


def test_a_cache_that_cannot_be_merged_fails_its_case_only(
    tmp_path: Path, fake_worker: Path
) -> None:
    project = write_project(tmp_path)
    write_behaviour(project, {"alpha-k2e_5": {"prepare": "corrupt_cache"}})
    plan_project(project)

    report = run_plan(project)

    outcomes = {case.case_id: case.status for case in report.cases}
    assert outcomes["alpha-k2e_5"] == "failed"
    assert outcomes["beta-base"] == "completed"
    merge_failed = _events(report.journal, "merge_failed")
    assert [event["case_id"] for event in merge_failed] == ["alpha-k2e_5"]
    assert Path(merge_failed[0]["private_cache"]).is_file()
    assert _events(report.journal, "launch_end")


def test_a_running_task_the_scheduler_says_ended_is_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hydromodpy.project.launch import slurm

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
        slurm,
        "scheduler_states",
        lambda root: {case_id: slurm.SchedulerState(case_id, "80_1", "OUT_OF_MEMORY", "0:125")},
    )

    status = {row.case_id: row.status for row in project_status(project).rows}

    assert status[case_id] == "failed"


def test_a_slurm_task_records_its_job_in_the_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hydromodpy.results.outcome import read_outcome
    from hydromodpy.results.storage.attempt import (
        claim_run_directory,
        scheduler_job_id_from_env,
    )

    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    monkeypatch.delenv("SLURM_ARRAY_JOB_ID", raising=False)
    monkeypatch.delenv("SLURM_ARRAY_TASK_ID", raising=False)
    assert scheduler_job_id_from_env() is None
    monkeypatch.setenv("SLURM_JOB_ID", "81")
    assert scheduler_job_id_from_env() == "81"
    monkeypatch.setenv("SLURM_ARRAY_JOB_ID", "80")
    monkeypatch.setenv("SLURM_ARRAY_TASK_ID", "3")

    claim = claim_run_directory(tmp_path / "p", "case", case_id="case", project="p")

    outcome = read_outcome(claim.run_dir)
    assert outcome is not None and outcome.scheduler_job_id == "80_3"
