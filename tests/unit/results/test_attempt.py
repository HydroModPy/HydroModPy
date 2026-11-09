"""Tests of attempt."""

from __future__ import annotations

import argparse
import json
import os
import socket
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import hydromodpy.results.outcome as outcome_module
import hydromodpy.results.storage.attempt as attempt_module
from hydromodpy.core.exceptions import ConfigError, WriteConflictError
from hydromodpy.core.state.layout import INTERNAL_DIRNAME, RUNS_DIRNAME
from hydromodpy.core.state.scratch import (
    SCRATCH_ROOT_ENV,
    run_scratch,
    scratch_dir_for,
    scratch_root_for,
)
from hydromodpy.results.catalog.indexer import index_new_runs
from hydromodpy.results.outcome import Outcome, effective_status, read_outcome, write_outcome
from hydromodpy.results.storage.attempt import (
    CaseAliveError,
    claim_reserved_directory,
    claim_run_directory,
    finish_attempt,
    record_request_id,
    start_over_if_changed,
    withdraw_claim,
)
from hydromodpy.results.storage.contract import (
    PARQUET_FILE_SUFFIX,
    README_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_OUTCOME_FILENAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.run_facts import RunFacts, read_facts
from hydromodpy.results.storage.run_store import RunStore
from tests._helpers.run_stores import claim_run
from tests._helpers.sealed_runs import make_project, seal_run

# An OOM kill writes nothing: the outcome still says ``running`` with a fresh
# pulse. On the host of the worker the process table proves the death, so the
# reader says ``stale`` at once and ``hmp catalog watch`` says ``dead``. Under
# ``HMP_SCRATCH_ROOT`` the preprocessing of a run leaves the project, as the
# solver folders already did.
DEAD_PID = 424242


def _running(run_dir: Path, *, host: str, pid: int) -> None:
    run_dir.mkdir(parents=True)
    write_outcome(
        run_dir,
        Outcome(
            case_id="case",
            attempt=1,
            attempt_id="a1",
            status="running",
            written_by="worker",
            started_at=datetime.now(UTC),
            host=host,
            pid=pid,
        ),
    )


def _dead_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(outcome_module, "process_is_alive", lambda pid: pid != DEAD_PID)


def test_a_dead_pid_of_this_host_reads_stale_with_a_fresh_pulse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dead_pid(monkeypatch)
    _running(tmp_path / "dead", host=socket.gethostname(), pid=DEAD_PID)
    _running(tmp_path / "alive", host=socket.gethostname(), pid=os.getpid())
    _running(tmp_path / "elsewhere", host="node-12", pid=DEAD_PID)

    assert effective_status(tmp_path / "dead") == "stale"
    assert effective_status(tmp_path / "alive") == "running"
    assert effective_status(tmp_path / "elsewhere") == "running"


def test_watch_says_dead_for_a_proven_death(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from hydromodpy.cli.commands.catalog import watch

    _dead_pid(monkeypatch)
    project = tmp_path / "p"
    (project / "project.toml").parent.mkdir(parents=True)
    (project / "project.toml").write_text("", encoding="utf-8")
    _running(project / "runs" / "case", host=socket.gethostname(), pid=DEAD_PID)
    args = argparse.Namespace(
        workspace=str(project), stale_minutes=5.0, format="json", verbosity=None
    )

    watch.run(args)

    rows = json.loads(capsys.readouterr().out)["data"]
    assert [(row["rel_dir"], row["dead"]) for row in rows] == [("runs/case", True)]


def test_the_preprocessing_scratch_honours_the_machine_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "campaign"
    project.mkdir()
    machine = tmp_path / "node-scratch"
    monkeypatch.delenv("HMP_RUN_SCRATCH", raising=False)
    monkeypatch.setenv(SCRATCH_ROOT_ENV, str(machine))

    assert scratch_root_for(project) == machine / "campaign"
    with run_scratch(project, "alpha-base") as key:
        folder = scratch_dir_for(project)
        assert folder == machine / "campaign" / key
    assert not (project / ".hmp" / "scratch").exists()


# The attempt protocol closes a failed run with ``outcome.json`` (``failed``,
# the error, the step, the end of the log) and a ``README.md`` rendered from
# that outcome. The tables written before the failure stay. ``manifest.json`` is
# never written: its presence would mean ``completed``. The attempt state under
# ``<run>/.hmp/`` is left as it was, for the retry. The indexer indexes the
# directory from its outcome alone.
CASE = "nancon_daily"


def _facts(claim) -> RunFacts:
    return RunFacts(
        sim_id=claim.sim_id,
        name=claim.name,
        case_id=CASE,
        project="demo",
        attempt=claim.attempt,
        attempt_id=claim.attempt_id,
        created_at=claim.started_at,
        started_at=claim.started_at,
        solver="modflow6",
    )


def _fail_a_run(project: Path) -> Path:
    claim = claim_run_directory(project, CASE, case_id=CASE, project="demo", site="nancon")
    with RunStore.open(claim.run_dir, facts=_facts(claim)) as store:
        index = pd.date_range("2020-01-01", periods=3, freq="D")
        store.write_timeseries(claim.sim_id, "P01", "head", pd.Series(np.ones(3), index=index))
        store.write_budget(claim.sim_id, 0, "z1", "recharge", 10.0, 0.0)
    finish_attempt(
        claim.run_dir,
        status="failed",
        step="run_solver",
        error=RuntimeError("mf6 did not converge at stress period 51"),
        exit_code=15,
        log_tail=["stress period 51 failed"],
    )
    return claim.run_dir


def test_a_failed_attempt_writes_its_outcome_and_readme_and_keeps_its_tables(tmp_path):
    project = make_project(tmp_path / "demo")

    run_dir = _fail_a_run(project)

    outcome = read_outcome(run_dir)
    assert outcome is not None
    assert outcome.status == "failed"
    assert outcome.step == "run_solver"
    assert outcome.exit_code == 15
    assert outcome.error is not None and outcome.error.type == "RuntimeError"
    assert outcome.log_tail == ["stress period 51 failed"]
    assert outcome.ended_at is not None
    readme = (run_dir / README_FILENAME).read_text(encoding="utf-8")
    assert "did not complete" in readme
    assert "stress period 51" in readme
    tables = sorted(path.name for path in (run_dir / TABLES_DIRNAME).iterdir())
    assert tables == [f"budgets{PARQUET_FILE_SUFFIX}", f"timeseries{PARQUET_FILE_SUFFIX}"]


def test_a_failed_attempt_has_no_manifest_and_reads_as_failed(tmp_path):
    project = make_project(tmp_path / "demo")

    run_dir = _fail_a_run(project)

    assert not (run_dir / RUN_MANIFEST_FILENAME).exists()
    assert effective_status(run_dir) == "failed"


def test_a_failed_attempt_keeps_its_attempt_state_for_the_retry(tmp_path):
    project = make_project(tmp_path / "demo")

    run_dir = _fail_a_run(project)

    assert (run_dir / INTERNAL_DIRNAME).is_dir()
    facts = read_facts(run_dir)
    assert facts is not None and facts.solver == "modflow6"


def test_a_failed_attempt_is_indexed_from_its_outcome(tmp_path):
    project = make_project(tmp_path / "demo")
    run_dir = _fail_a_run(project)

    report = index_new_runs(project)

    assert f"{RUNS_DIRNAME}/{CASE}" in set(report.indexed), report
    assert (run_dir / RUN_OUTCOME_FILENAME).is_file()


# SIGKILL or the OOM killer stop a worker between two pulses: its outcome still
# says ``running`` and the pulse is younger than the stale limit. On the same
# host the process table answers: a dead pid means the attempt is over, and the
# next claim takes attempt 2 in the same directory. A live pid, or another host,
# keeps the case refused.
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


# The claim carries no identity. It says whether it created the directory, it can be
# withdrawn without a trace, an attempt k + 1 starts over when the request id of
# attempt k differs, and every name it creates or resumes follows the rule.


def _failed(run_dir: Path, *, request_id: str | None = None) -> None:
    """Close the attempt in *run_dir* as failed, with *request_id* in its outcome."""
    if request_id is not None:
        record_request_id(run_dir, request_id)
    (run_dir / "logs").mkdir(exist_ok=True)
    (run_dir / "logs" / "run.log").write_text("attempt log\n", encoding="utf-8")
    finish_attempt(run_dir, status="failed", error=RuntimeError("stop"))


def _tree(folder: Path) -> dict[str, bytes | None]:
    """Every entry under *folder*, files with their bytes."""
    return {
        entry.relative_to(folder).as_posix(): entry.read_bytes() if entry.is_file() else None
        for entry in sorted(folder.rglob("*"))
    }


@pytest.mark.parametrize(
    ("before", "created", "attempt"),
    [
        pytest.param("nothing", True, 1, id="a new directory"),
        pytest.param("sealed", True, 1, id="a new version after a sealed one"),
        pytest.param("failed", False, 2, id="a retry of a failed attempt"),
    ],
)
def test_a_claim_says_whether_it_created_its_directory(
    tmp_path: Path, before: str, created: bool, attempt: int
) -> None:
    project = make_project(tmp_path / "demo")
    if before == "sealed":
        seal_run(project, "case")
    if before == "failed":
        _failed(claim_run_directory(project, "case", case_id="case", project="demo").run_dir)

    claim = claim_run_directory(project, "case", case_id="case", project="demo")

    assert claim.created is created
    assert claim.attempt == attempt
    assert claim.run_dir.name == ("case.v2" if before == "sealed" else "case")


@pytest.mark.parametrize("before", ["nothing", "sealed"])
def test_a_withdrawn_new_directory_leaves_nothing(tmp_path: Path, before: str) -> None:
    project = make_project(tmp_path / "demo")
    if before == "sealed":
        seal_run(project, "case")
    runs_before = sorted(path.name for path in (project / RUNS_DIRNAME).glob("*"))
    claim = claim_run_directory(project, "case", case_id="case", project="demo")
    (claim.run_dir / "request.json").write_text("{}", encoding="utf-8")

    withdraw_claim(claim)

    assert sorted(path.name for path in (project / RUNS_DIRNAME).glob("*")) == runs_before


@pytest.mark.parametrize("starts_over", [False, True], ids=["resumed", "started over"])
def test_a_withdrawn_retry_puts_back_the_attempt_it_followed(
    tmp_path: Path, starts_over: bool
) -> None:
    project = make_project(tmp_path / "demo")
    first = claim_run_directory(project, "case", case_id="case", project="demo")
    (first.run_dir / "fields.zarr").mkdir()
    (first.run_dir / "fields.zarr" / "chunk").write_bytes(b"partial")
    _failed(first.run_dir, request_id="a" * 64)
    before = _tree(first.run_dir)

    retry = claim_run_directory(project, "case", case_id="case", project="demo")
    if starts_over:
        retry = start_over_if_changed(retry, "b" * 64)
        assert not (retry.run_dir / "fields.zarr").exists()
    (retry.run_dir / "request.json").write_text("{}", encoding="utf-8")
    (retry.run_dir / "logs").mkdir(exist_ok=True)
    (retry.run_dir / "logs" / "run.log").write_text("retry log\n", encoding="utf-8")

    withdraw_claim(retry)

    assert _tree(first.run_dir) == before
    assert not (first.run_dir / "attempts").exists()


@pytest.mark.parametrize("request_b", ["a" * 64, "b" * 64], ids=["same request", "another request"])
def test_a_withdrawn_retry_puts_back_what_attempt_k_was_asked(
    tmp_path: Path, request_b: str
) -> None:
    """The order of a run: the claim writes its documents, then compares, then withdraws."""
    project = make_project(tmp_path / "demo")
    first = claim_run_directory(project, "case", case_id="case", project="demo")
    (first.run_dir / "config.toml").write_text("asked = 'A'\n", encoding="utf-8")
    (first.run_dir / "request.json").write_text('{"asked": "A"}', encoding="utf-8")
    _failed(first.run_dir, request_id="a" * 64)
    before = _tree(first.run_dir)

    retry = claim_run_directory(project, "case", case_id="case", project="demo")
    (retry.run_dir / "config.toml").write_text("asked = 'B'\n", encoding="utf-8")
    (retry.run_dir / "request.json").write_text('{"asked": "B"}', encoding="utf-8")
    record_request_id(retry.run_dir, request_b)
    retry = start_over_if_changed(retry, request_b)
    assert (retry.run_dir / "config.toml").read_text(encoding="utf-8") == "asked = 'B'\n"

    withdraw_claim(retry)

    assert _tree(first.run_dir) == before
    assert not (first.run_dir / "attempts").exists()


def test_a_withdrawn_first_attempt_of_a_reserved_directory_keeps_the_reservation(
    tmp_path: Path,
) -> None:
    run_dir = make_project(tmp_path / "demo") / RUNS_DIRNAME / "promoted"
    run_dir.mkdir(parents=True)
    claim = claim_reserved_directory(run_dir, case_id="promoted", project="demo")

    withdraw_claim(claim)

    assert run_dir.is_dir() and list(run_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("recorded", "now", "starts_over"),
    [
        pytest.param("a" * 64, "a" * 64, False, id="the same request resumes"),
        pytest.param("a" * 64, "b" * 64, True, id="another request starts over"),
        pytest.param(None, "a" * 64, True, id="an outcome without request id starts over"),
    ],
)
def test_a_retry_starts_over_when_its_request_changed(
    tmp_path: Path, recorded: str | None, now: str, starts_over: bool
) -> None:
    project = make_project(tmp_path / "demo")
    first = claim_run_directory(project, "case", case_id="case", project="demo")
    (first.run_dir / "fields.zarr").mkdir()
    _failed(first.run_dir, request_id=recorded)
    retry = claim_run_directory(project, "case", case_id="case", project="demo")

    after = start_over_if_changed(retry, now)

    assert after.resumed is not starts_over
    assert (after.sim_id != retry.sim_id) is starts_over
    assert (retry.run_dir / "fields.zarr").exists() is not starts_over
    assert (retry.run_dir / "attempts" / "1" / "fields.zarr").exists() is starts_over
    outcome = read_outcome(retry.run_dir)
    assert outcome is not None and outcome.sim_id == after.sim_id


def test_a_first_attempt_never_starts_over(tmp_path: Path) -> None:
    claim = claim_run_directory(make_project(tmp_path / "demo"), "case", case_id="c", project="d")

    assert start_over_if_changed(claim, "a" * 64) is claim


def test_the_request_id_is_written_into_the_running_outcome(tmp_path: Path) -> None:
    claim = claim_run_directory(make_project(tmp_path / "demo"), "case", case_id="c", project="d")

    record_request_id(claim.run_dir, "c" * 64)

    outcome = read_outcome(claim.run_dir)
    assert outcome is not None
    assert (outcome.request_id, outcome.status, outcome.sim_id) == (
        "c" * 64,
        "running",
        claim.sim_id,
    )


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("Case A", id="capital and space"),
        pytest.param("con", id="reserved on Windows"),
        pytest.param("c" * 41, id="forty-one characters"),
        pytest.param("COM1.v2", id="a version of a refused stem"),
    ],
)
def test_a_claim_refuses_a_name_off_the_rule_and_writes_nothing(tmp_path: Path, name: str) -> None:
    project = make_project(tmp_path / "demo")

    with pytest.raises(ConfigError, match="name"):
        claim_run_directory(project, name, case_id=name, project="demo")

    assert not (project / RUNS_DIRNAME).exists()


def test_a_claim_names_the_folder_a_disk_without_case_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a disk that ignores case, a folder of 2.0 in capitals holds the folded name."""
    project = make_project(tmp_path / "demo")
    (project / RUNS_DIRNAME / "J0014010-base").mkdir(parents=True)
    real_mkdir = os.mkdir

    def mkdir_without_case(path, *args, **kwargs):
        if Path(path).name == "j0014010-base":
            raise FileExistsError(path)
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(os, "mkdir", mkdir_without_case)

    with pytest.raises(WriteConflictError, match="runs/J0014010-base holds the name"):
        claim_run_directory(project, "j0014010-base", case_id="j0014010-base", project="demo")

    assert sorted(path.name for path in (project / RUNS_DIRNAME).iterdir()) == ["J0014010-base"]
