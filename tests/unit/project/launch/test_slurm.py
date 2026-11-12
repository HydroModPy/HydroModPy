"""``write_slurm_array`` writes a frozen SLURM job for the current plan, and a task runs it.

``jobs/<stamp>-slurm/`` holds ``prepare.sh``, ``array.sh`` and ``cases.txt``:
line N of ``cases.txt`` is the case task N runs, in the order of the plan. A
job directory is written once, from a current plan only. A task runs ``hmp run``
with the flags the local launcher would pick, and ``finish_task`` closes the
directory of a worker that left ``running`` behind.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.cli.commands import run as run_command
from hydromodpy.core.exceptions import ConfigError, JobUsageError
from hydromodpy.project.launch import slurm
from hydromodpy.project.launch.journal import case_for_task, read_case_list
from hydromodpy.project.launch.slurm import finish_task, task_flags, write_lock, write_slurm_array
from hydromodpy.results.outcome import Outcome, read_outcome, write_outcome
from hydromodpy.results.session.descriptor import read_session, write_session
from hydromodpy.results.storage.attempt import claim_run_directory, finish_attempt
from hydromodpy.workflow.steps.sequence import standard_steps
from hydromodpy.workflow.window import model_phase_index, resolve_step_index
from tests._helpers.session_documents import session_descriptor
from tests.unit.project.launch._helpers import (
    PLAN_HASH,
    PROJECT_TOML,
    STAMP,
    dead_pid,
    planned_project,
)

CASES = ("j001-base", "j002-base", "j003-calage")
"""The cases of the plan, named as the plan names them: folded to a run name."""


def _planned(root: Path, **kwargs):
    return planned_project(root, cases=CASES, **kwargs)


def test_job_scripts_and_cases(tmp_path: Path) -> None:
    root = tmp_path / "bretagne"
    stored = _planned(root)

    job = write_slurm_array(root, stamp=STAMP)

    assert job.directory == root / "jobs" / f"{STAMP}-slurm"
    assert {p.name for p in job.directory.iterdir()} >= {"prepare.sh", "array.sh", "cases.txt"}
    assert (job.prepare_sh, job.array_sh, job.cases_txt) == (
        job.directory / "prepare.sh",
        job.directory / "array.sh",
        job.directory / "cases.txt",
    )
    expected = [f"plan/{PLAN_HASH}/{case.config_path}" for case in stored.cases]
    assert read_case_list(job.directory) == expected
    assert job.cases_txt.read_text().splitlines() == expected
    for line in expected:
        assert (root / line).is_file()
    assert job.n_cases == 3 and job.plan_hash == PLAN_HASH


def test_a_job_directory_is_written_once(tmp_path: Path) -> None:
    root = tmp_path / "p"
    _planned(root)
    job = write_slurm_array(root, stamp=STAMP)
    before = job.cases_txt.read_bytes()

    with pytest.raises(JobUsageError, match="written once"):
        write_slurm_array(root, stamp=STAMP)

    assert job.cases_txt.read_bytes() == before
    assert not [p for p in (root / "jobs").iterdir() if p.name.startswith(".staging")]


def test_waiting_job_keeps_its_cases(tmp_path: Path) -> None:
    root = tmp_path / "p"
    _planned(root)
    job = write_slurm_array(root, stamp=STAMP)
    first = read_case_list(job.directory)

    (root / "plan" / "current").write_text("ffffffffffffffff\n")

    assert read_case_list(job.directory) == first
    assert case_for_task(root, job.directory.name, 2) == root / first[1]


def test_without_a_plan_nothing_is_written(tmp_path: Path) -> None:
    root = tmp_path / "p"
    root.mkdir()
    (root / "project.toml").write_text(PROJECT_TOML.format(threads=1, prepare=1))

    with pytest.raises(FileNotFoundError, match="no plan"):
        write_slurm_array(root, stamp=STAMP)
    assert not (root / "jobs").exists()


def test_stale_plan_refused(tmp_path: Path) -> None:
    root = tmp_path / "p"
    _planned(root)
    with (root / "project.toml").open("a") as handle:
        handle.write("# edited after the plan\n")

    with pytest.raises(ConfigError, match="hmp project plan"):
        write_slurm_array(root, stamp=STAMP)
    assert not (root / "jobs").exists()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"partition": "normal; rm -rf /"}, "partition"),
        ({"walltime": "12h"}, "not a SLURM time"),
        ({"walltime": "10"}, "stopped at its start"),
        ({"threads_per_case": 0}, "threads_per_case"),
        ({"prepare_parallel": 0}, "prepare_parallel"),
        ({"prepare_parallel": 99}, "above 8"),
    ],
)
def test_invalid_options_are_refused(tmp_path: Path, kwargs: dict, message: str) -> None:
    root = tmp_path / "p"
    _planned(root)

    with pytest.raises(ConfigError, match=message):
        write_slurm_array(root, stamp=STAMP, **kwargs)
    assert not (root / "jobs").exists()


def test_stamp_and_path_checked(tmp_path: Path) -> None:
    root = tmp_path / "p"
    _planned(root)
    with pytest.raises(JobUsageError, match="stamp"):
        write_slurm_array(root, stamp="today")

    spaced = tmp_path / "with space"
    _planned(spaced)
    with pytest.raises(ConfigError, match="#SBATCH"):
        write_slurm_array(spaced, stamp=STAMP)


CALIBRATION = "j003-calage"


def _project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "p"
    stored = _planned(root, calibration_parallel={CALIBRATION: 2})
    return root, stored.directory


def _parsed(case: Path, flags: list[str]) -> argparse.Namespace:
    subparsers = argparse.ArgumentParser(prog="hmp").add_subparsers()
    return run_command.register(subparsers).parse_args([str(case), *flags])


def test_prepare_stops_after_load_data(tmp_path: Path) -> None:
    root, plan = _project(tmp_path)

    flags = task_flags(root, plan / "j001-base.toml", phase="prepare")

    assert flags == ["--until", "load_data"]
    args = _parsed(plan / "j001-base.toml", flags)
    steps = standard_steps()
    assert resolve_step_index(args.until_step, steps) < model_phase_index(steps)


def test_calibration_prepared_as_simulation(tmp_path: Path) -> None:
    root, plan = _project(tmp_path)

    flags = task_flags(root, plan / f"{CALIBRATION}.toml", phase="prepare")

    assert flags == ["--until", "load_data", "--set", "workflow.mode=simulation"]
    args = _parsed(plan / f"{CALIBRATION}.toml", flags)
    assert args.set_overrides == ["workflow.mode=simulation"]


def test_first_solve_flags(tmp_path: Path) -> None:
    root, plan = _project(tmp_path)
    case = plan / "j001-base.toml"

    assert task_flags(root, case, phase="solve") == []
    (root / "hydromodpy.lock").write_text("pinned\n")
    assert task_flags(root, case, phase="solve") == ["--frozen"]


def test_failed_simulation_resumes(tmp_path: Path) -> None:
    root, plan = _project(tmp_path)
    (root / "hydromodpy.lock").write_text("pinned\n")
    claim = claim_run_directory(root, "j001-base", case_id="j001-base", project="p")
    finish_attempt(claim.run_dir, status="failed", exit_code=1, error=RuntimeError("x"))

    flags = task_flags(root, plan / "j001-base.toml", phase="solve")

    assert flags == ["--frozen", "--resume", "j001-base"]
    assert _parsed(plan / "j001-base.toml", flags).resume == "j001-base"


def test_a_calibration_never_takes_resume(tmp_path: Path) -> None:
    root, plan = _project(tmp_path)
    (root / "hydromodpy.lock").write_text("pinned\n")
    claim = claim_run_directory(root, CALIBRATION, case_id=CALIBRATION, project="p")
    finish_attempt(claim.run_dir, status="failed", exit_code=1, error=RuntimeError("x"))

    assert task_flags(root, plan / f"{CALIBRATION}.toml", phase="solve") == ["--frozen"]


def test_unknown_case_or_phase_refused(tmp_path: Path) -> None:
    root, plan = _project(tmp_path)
    stray = plan / "j999-base.toml"
    stray.write_text('[site]\nname = "j999"\n')

    with pytest.raises(JobUsageError, match="not a case of plan"):
        task_flags(root, stray, phase="solve")
    with pytest.raises(JobUsageError, match="phase"):
        task_flags(root, plan / "j001-base.toml", phase="data")


def test_lock_from_case_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, plan = _project(tmp_path)
    seen: dict[str, Path] = {}

    def data_dir(case_path: Path) -> Path:
        seen["case"] = case_path
        return tmp_path / "workspace" / "data"

    def write(project_root: Path, data: Path) -> Path:
        seen["root"], seen["data"] = project_root, data
        return project_root / "hydromodpy.lock"

    monkeypatch.setattr(slurm, "workspace_data_dir", data_dir)
    monkeypatch.setattr("hydromodpy.project.launch.lockfile.write_project_lockfile", write)

    path = write_lock(root, Path("plan") / plan.name / "j001-base.toml")

    assert path == root.resolve() / "hydromodpy.lock"
    assert seen["case"] == root.resolve() / "plan" / plan.name / "j001-base.toml"
    assert seen["data"] == tmp_path / "workspace" / "data"


def _claimed(tmp_path: Path, *, pid: int, host: str | None = None) -> tuple[Path, Path]:
    root = tmp_path / "p"
    stored = _planned(root)
    claim = claim_run_directory(root, "j001-base", case_id="j001-base", project="p")
    outcome = read_outcome(claim.run_dir)
    assert outcome is not None
    update: dict[str, object] = {"pid": pid}
    if host is not None:
        update["host"] = host
    write_outcome(claim.run_dir, outcome.model_copy(update=update))
    return root, stored.directory / "j001-base.toml"


@pytest.mark.allow_subprocess
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_finish_task_reads_signal_and_log(tmp_path: Path) -> None:
    root, case_toml = _claimed(tmp_path, pid=dead_pid())
    log = tmp_path / "task.out"
    log.write_text("".join(f"line {i}\n" for i in range(100)))

    outcome = finish_task(root, case_toml, exit_code=143, log_path=log, job_id="7_1")

    assert outcome is not None and outcome.signal == 15 and outcome.exit_code == 143
    assert outcome.log_tail[-1] == "line 99" and len(outcome.log_tail) == 40
    assert outcome.error is not None and "without writing its outcome" in outcome.error.message


@pytest.mark.allow_subprocess
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_finish_task_spares_live_worker(tmp_path: Path) -> None:
    root, case_toml = _claimed(tmp_path / "alive", pid=os.getpid())
    assert finish_task(root, case_toml, exit_code=1) is None
    outcome = read_outcome(root / "runs" / "j001-base")
    assert outcome is not None and outcome.status == "running"

    root, case_toml = _claimed(
        tmp_path / "foreign", pid=dead_pid(), host="not-" + socket.gethostname()
    )
    assert finish_task(root, case_toml, exit_code=1) is None
    outcome = read_outcome(root / "runs" / "j001-base")
    assert outcome is not None and outcome.status == "running"


@pytest.mark.allow_subprocess
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_finish_task_without_run(tmp_path: Path) -> None:
    root = tmp_path / "p"
    stored = _planned(root)

    assert finish_task(root, stored.directory / "j001-base.toml", exit_code=2) is None
    assert not (root / "runs").exists()


@pytest.mark.allow_subprocess
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_running_session_is_closed(tmp_path: Path) -> None:
    root = tmp_path / "p"
    stored = _planned(root)
    session = root / "sessions" / "j003-calage"
    session.mkdir(parents=True)
    started = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
    write_session(
        session,
        session_descriptor(
            "j003-calage",
            session_id="s1",
            config_hash="h",
            hydromodpy_version="test",
            method="cmaes",
            started_at=started,
        ),
    )
    write_outcome(
        session,
        Outcome(
            case_id="j003-calage",
            attempt=1,
            attempt_id="a1",
            status="running",
            written_by="worker",
            started_at=started,
            host=socket.gethostname(),
            pid=dead_pid(),
        ),
    )
    log = tmp_path / "task.out"
    log.write_text("trial 12 diverged\n")

    outcome = finish_task(
        root, stored.directory / "j003-calage.toml", exit_code=137, log_path=log, job_id="9_3"
    )

    assert outcome is not None and outcome.written_by == "trap" and outcome.signal == 9
    assert read_session(session).status == "failed"
    on_disk = read_outcome(session)
    assert on_disk is not None and on_disk.status == "failed"
    assert on_disk.scheduler_job_id == "9_3" and on_disk.log_tail == ["trial 12 diverged"]
    assert (session / "logs" / "job-9_3.out").is_file()
    assert not (session / "README.md").exists()
