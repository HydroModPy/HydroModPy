"""A worker killed without a word leaves a fresh pulse; on its host, its death is proven.

SIGKILL or the OOM killer stop a worker between two pulses: its outcome still
says ``running`` and the pulse is younger than the stale limit. On the same
host the process table answers: a dead pid means the attempt is over, and the
next claim takes attempt 2 in the same directory. A live pid, or another host,
keeps the case refused."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy.results.outcome as outcome_module
import hydromodpy.results.storage.attempt as attempt_module
from hydromodpy.results.outcome import read_outcome, write_outcome
from hydromodpy.results.storage.attempt import CaseAliveError, claim_run_directory
from tests._helpers.run_stores import claim_run

WORKER_PID = 424242


def _written_by_another_worker(run_dir: Path, *, host: str | None = None) -> None:
    outcome = read_outcome(run_dir)
    assert outcome is not None and outcome.status == "running"
    update: dict[str, object] = {"pid": WORKER_PID}
    if host is not None:
        update["host"] = host
    write_outcome(run_dir, outcome.model_copy(update=update))


def _process_table(monkeypatch: pytest.MonkeyPatch, *, alive: bool) -> None:
    # The claim and the reader of the outcome both ask the process table.
    for module in (attempt_module, outcome_module):
        monkeypatch.setattr(
            module, "process_is_alive", lambda pid: alive if pid == WORKER_PID else True
        )


def _claim_again(project: Path):
    return claim_run_directory(project, "case", case_id="case", project=project.name)


def test_a_dead_pid_of_this_host_ends_the_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "p"
    first = claim_run(project, "case")
    _written_by_another_worker(first.run_dir)
    _process_table(monkeypatch, alive=False)

    second = _claim_again(project)

    assert second.run_dir == first.run_dir
    assert second.attempt == 2


def test_a_live_pid_keeps_the_case_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "p"
    first = claim_run(project, "case")
    _written_by_another_worker(first.run_dir)
    _process_table(monkeypatch, alive=True)

    with pytest.raises(CaseAliveError, match="pulse is fresh"):
        _claim_again(project)


def test_another_host_keeps_the_case_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "p"
    first = claim_run(project, "case")
    _written_by_another_worker(first.run_dir, host="another-node")
    _process_table(monkeypatch, alive=False)

    with pytest.raises(CaseAliveError, match="pulse is fresh"):
        _claim_again(project)


@pytest.mark.allow_subprocess
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
