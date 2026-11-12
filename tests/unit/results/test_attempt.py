"""The attempt protocol of a run folder: claim, retry, stop, close, and the names a claim takes.

A claim reserves ``runs/<name>`` for one attempt. A failed attempt is closed with its
outcome and README and retried in place, a stopped one reads ``aborted``, and a name
follows the version rule (``name``, ``name.v2``, ...) whatever the trash holds.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

import hydromodpy.core.state.host as host_module
import hydromodpy.results.storage.attempt as attempt_module
from hydromodpy.cli.exit_codes import EXIT_AMBIGUOUS_REFERENCE
from hydromodpy.core.exceptions import (
    ConfigError,
    NothingThereError,
    ResumeError,
    WriteConflictError,
)
from hydromodpy.core.io import filesystem
from hydromodpy.core.runtime.interrupts import (
    STOP_FLAG_SCHEMA,
    StopRequested,
    TerminationRequested,
    raise_if_stop_requested,
)
from hydromodpy.core.state.layout import INTERNAL_DIRNAME, RUNS_DIRNAME, STOP_FLAG_FILENAME
from hydromodpy.core.state.scratch import (
    SCRATCH_ROOT_ENV,
    run_scratch,
    scratch_dir_for,
    scratch_root_for,
)
from hydromodpy.results.catalog.indexer import index_new_runs
from hydromodpy.results.catalog.registration import NameTakenError, reserve_version_dirname
from hydromodpy.results.outcome import Outcome, effective_status, read_outcome, write_outcome
from hydromodpy.results.storage.attempt import (
    CaseAliveError,
    claim_reserved_directory,
    claim_run_directory,
    close_attempt_of_process,
    close_sealed_attempt,
    finish_attempt,
    record_request_id,
    refuse_resume_if_changed,
    request_stop,
    scheduler_job_id_from_env,
    signal_of,
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
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.results.trash import gc_trash, list_trash, read_tombstones, trash_run
from hydromodpy.solver.base.simulation_config import SimulationConfig
from tests._helpers.run_stores import claim_run, open_run_store
from tests._helpers.sealed_runs import make_project, seal_run, write_attempt
from tests._helpers.windows_os import WindowsOs  # noqa: I001

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
    monkeypatch.setattr(host_module, "process_is_alive", lambda pid: pid != DEAD_PID)


def test_dead_pid_reads_stale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _dead_pid(monkeypatch)
    _running(tmp_path / "dead", host=socket.gethostname(), pid=DEAD_PID)
    _running(tmp_path / "alive", host=socket.gethostname(), pid=os.getpid())
    _running(tmp_path / "elsewhere", host="node-12", pid=DEAD_PID)

    assert effective_status(tmp_path / "dead") == "stale"
    assert effective_status(tmp_path / "alive") == "running"
    assert effective_status(tmp_path / "elsewhere") == "running"


def test_watch_says_dead(
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


def test_scratch_honours_machine_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "campaign"
    project.mkdir()
    machine = tmp_path / "node-scratch"
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


def test_failed_attempt_outcome_and_tables(tmp_path):
    run_dir = _fail_a_run(make_project(tmp_path / "demo"))

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


def test_failed_attempt_has_no_manifest(tmp_path):
    run_dir = _fail_a_run(make_project(tmp_path / "demo"))

    # A manifest would make the run read as completed.
    assert not (run_dir / RUN_MANIFEST_FILENAME).exists()
    assert effective_status(run_dir) == "failed"


def test_failed_attempt_keeps_state(tmp_path):
    run_dir = _fail_a_run(make_project(tmp_path / "demo"))

    assert (run_dir / INTERNAL_DIRNAME).is_dir()
    facts = read_facts(run_dir)
    assert facts is not None and facts.solver == "modflow6"


def test_failed_attempt_is_indexed(tmp_path):
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
    for module in (attempt_module, host_module):
        monkeypatch.setattr(
            module, "process_is_alive", lambda pid: alive if pid == WORKER_PID else True
        )


def _claim_again(project: Path):
    return claim_run_directory(project, "case", case_id="case", project=project.name)


def test_dead_pid_ends_attempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "p"
    first = claim_run(project, "case")
    _written_by_another_worker(first.run_dir)
    _process_table(monkeypatch, alive=False)

    second = _claim_again(project)

    assert second.run_dir == first.run_dir
    assert second.attempt == 2


LIVE_WORKERS = [
    pytest.param(None, True, id="live pid"),
    pytest.param("another-node", False, id="another host"),
]


@pytest.mark.parametrize(("host", "alive"), LIVE_WORKERS)
def test_live_worker_keeps_case_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: str | None, alive: bool
) -> None:
    project = tmp_path / "p"
    first = claim_run(project, "case")
    _written_by_another_worker(first.run_dir, host=host)
    _process_table(monkeypatch, alive=alive)

    with pytest.raises(CaseAliveError, match="pulse is fresh"):
        _claim_again(project)


@pytest.mark.allow_subprocess
def test_slurm_job_in_outcome(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
def test_claim_created_flag(tmp_path: Path, before: str, created: bool, attempt: int) -> None:
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
def test_withdrawn_retry_restores_attempt(tmp_path: Path, starts_over: bool) -> None:
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
def test_withdrawn_retry_restores_request(tmp_path: Path, request_b: str) -> None:
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


def test_withdrawn_reserved_directory(
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
def test_retry_starts_over_on_change(
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


def test_request_id_in_running_outcome(tmp_path: Path) -> None:
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
def test_name_refusals(tmp_path: Path, name: str) -> None:
    project = make_project(tmp_path / "demo")

    with pytest.raises(ConfigError, match="name"):
        claim_run_directory(project, name, case_id=name, project="demo")

    assert not (project / RUNS_DIRNAME).exists()


def test_name_folded_on_caseless_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """On a disk that ignores case, a folder of a pre-release in capitals holds the folded name."""
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


# A run is asked to stop by a flag in its attempt state. The flag stops it at the
# next check, the outcome reads aborted with the error StopRequested and no
# signal, the next attempt files the flag under attempts/<k>/, and a resume asked
# on a request that changed since the stop is refused.


def _stop_flag(run_dir: Path) -> Path:
    return run_dir / INTERNAL_DIRNAME / STOP_FLAG_FILENAME


def test_run_stopped_by_flag(tmp_path: Path) -> None:
    claim = claim_run_directory(make_project(tmp_path / "demo"), "case", case_id="c", project="d")
    at = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)

    flag = request_stop(claim.run_dir, now=at)

    assert flag == _stop_flag(claim.run_dir)
    document = json.loads(flag.read_text(encoding="utf-8"))
    assert document == {
        "schema": STOP_FLAG_SCHEMA,
        "at": "2026-11-10T08:00:00+00:00",
        "host": socket.gethostname(),
    }
    with pytest.raises(StopRequested, match="stop requested at 2026-11-10T08:00:00"):
        raise_if_stop_requested(flag)


def test_repeated_stop_rewrites_date(tmp_path: Path) -> None:
    claim = claim_run_directory(make_project(tmp_path / "demo"), "case", case_id="c", project="d")
    request_stop(claim.run_dir, now=datetime(2026, 11, 10, 8, 0, tzinfo=UTC))

    flag = request_stop(claim.run_dir, now=datetime(2026, 11, 10, 9, 0, tzinfo=UTC))

    assert json.loads(flag.read_text(encoding="utf-8"))["at"] == "2026-11-10T09:00:00+00:00"


def _session(folder: Path, status: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder.mkdir(parents=True)
    (folder / "session.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        attempt_module, "read_session", lambda directory: argparse.Namespace(status=status)
    )
    return folder


def test_session_stopped_by_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session(tmp_path / "sessions" / "calib", "running", monkeypatch)

    assert request_stop(session) == _stop_flag(session)


@pytest.mark.parametrize(
    ("state", "message"),
    [
        pytest.param("completed", "runs/case is completed, there is nothing to stop", id="sealed"),
        pytest.param("failed", "runs/case is failed, there is nothing to stop", id="failed"),
        pytest.param("aborted", "runs/case is aborted, there is nothing to stop", id="aborted"),
        pytest.param("absent", "runs/case does not exist, there is nothing to stop", id="absent"),
        pytest.param(
            "closed session", "sessions/calib is completed, there is nothing to stop", id="session"
        ),
    ],
)
def test_nothing_to_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str, message: str
) -> None:
    project = make_project(tmp_path / "demo")
    folder = project / RUNS_DIRNAME / "case"
    if state == "completed":
        seal_run(project, "case")
    elif state in ("failed", "aborted"):
        claim = claim_run_directory(project, "case", case_id="c", project="d")
        finish_attempt(claim.run_dir, status=state, error=RuntimeError("boom"))
    elif state == "closed session":
        folder = _session(project / "sessions" / "calib", "completed", monkeypatch)

    with pytest.raises(NothingThereError, match=message):
        request_stop(folder)
    assert not _stop_flag(folder).exists()


@pytest.mark.parametrize("fresh", [False, True], ids=["resumed", "fresh"])
def test_next_attempt_files_stop_flag(tmp_path: Path, fresh: bool) -> None:
    project = make_project(tmp_path / "demo")
    first = claim_run_directory(project, "case", case_id="case", project="demo")
    flag = request_stop(first.run_dir)
    finish_attempt(first.run_dir, status="aborted", error=StopRequested("stop requested at x"))
    written = flag.read_bytes()

    retry = claim_run_directory(project, "case", case_id="case", project="demo", fresh=fresh)

    assert not _stop_flag(retry.run_dir).exists()
    assert (retry.run_dir / "attempts" / "1" / STOP_FLAG_FILENAME).read_bytes() == written
    raise_if_stop_requested(_stop_flag(retry.run_dir))


def test_withdrawn_retry_restores_flag(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    first = claim_run_directory(project, "case", case_id="case", project="demo")
    request_stop(first.run_dir)
    finish_attempt(first.run_dir, status="aborted", error=StopRequested("stop requested at x"))
    before = _tree(first.run_dir)

    withdraw_claim(claim_run_directory(project, "case", case_id="case", project="demo"))

    assert _tree(first.run_dir) == before


def test_stopped_attempt_reads_aborted(tmp_path: Path) -> None:
    claim = claim_run_directory(make_project(tmp_path / "demo"), "case", case_id="c", project="d")
    error = StopRequested("stop requested at 2026-11-10T08:00:00+00:00")

    finish_attempt(claim.run_dir, status="aborted", error=error, signal=signal_of(error))

    outcome = read_outcome(claim.run_dir)
    assert outcome.status == "aborted" and outcome.signal is None
    assert outcome.error.type == "StopRequested"
    assert outcome.error.message == "stop requested at 2026-11-10T08:00:00+00:00"
    assert effective_status(claim.run_dir) == "aborted"


@pytest.mark.parametrize(
    ("error", "signal"),
    [
        pytest.param(StopRequested("stop requested at x"), None, id="a stop"),
        pytest.param(TerminationRequested("signal 15"), 15, id="SIGTERM"),
        pytest.param(KeyboardInterrupt(), 2, id="SIGINT"),
        pytest.param(RuntimeError("boom"), None, id="an error"),
        pytest.param(None, None, id="nothing"),
    ],
)
def test_signal_of_error(error, signal) -> None:
    assert signal_of(error) == signal


@pytest.mark.parametrize(
    ("recorded", "now", "refused"),
    [
        pytest.param("a" * 64, "a" * 64, False, id="the same request resumes"),
        pytest.param("a" * 64, "b" * 64, True, id="another request is refused"),
        pytest.param(None, "a" * 64, False, id="nothing recorded resumes"),
    ],
)
def test_resume_on_changed_request(
    tmp_path: Path, recorded: str | None, now: str, refused: bool
) -> None:
    project = make_project(tmp_path / "demo")
    first = claim_run_directory(project, "case", case_id="case", project="demo")
    _failed(first.run_dir, request_id=recorded)
    retry = claim_run_directory(project, "case", case_id="case", project="demo")

    if not refused:
        refuse_resume_if_changed(retry, now)
        return
    with pytest.raises(ResumeError, match="without --resume to start it over") as raised:
        refuse_resume_if_changed(retry, now)
    assert "runs/case cannot resume: an input or a key of the request changed" in str(raised.value)


@pytest.mark.parametrize("fresh", [False, True], ids=["first attempt", "fresh retry"])
def test_attempt_without_resume_never_refused(tmp_path: Path, fresh: bool) -> None:
    project = make_project(tmp_path / "demo")
    claim = claim_run_directory(project, "case", case_id="case", project="demo")
    if fresh:
        _failed(claim.run_dir, request_id="a" * 64)
        claim = claim_run_directory(project, "case", case_id="case", project="demo", fresh=True)

    refuse_resume_if_changed(claim, "b" * 64)


def _long_project(tmp_path: Path, length: int) -> Path:
    """A project folder of at least ``length`` characters (the scratch root is already long)."""
    base = str(tmp_path / "p")
    return Path(base + "x" * max(length - len(base), 0))


def test_long_folder_refused_on_windows(tmp_path, monkeypatch):
    project = _long_project(tmp_path, 120)
    monkeypatch.setattr(filesystem, "os", WindowsOs())

    with pytest.raises(ConfigError, match="is \\d+ characters long.*99 characters at most"):
        claim_run_directory(project, "case", case_id="case", project="p")

    assert not project.exists()


def test_long_folder_claimed_on_linux(tmp_path):
    project = _long_project(tmp_path, 120)

    claim = claim_run_directory(project, "case", case_id="case", project="p")

    assert claim.run_dir.is_dir()


def test_unreadable_outcome_is_skipped(tmp_path: Path) -> None:
    """The attempt of this process is still closed, past a folder whose outcome cannot be read."""
    broken = tmp_path / "runs" / "a_broken"
    broken.mkdir(parents=True)
    (broken / "outcome.json").write_text("{not json", encoding="utf-8")
    run_dir = write_attempt(
        tmp_path, "runs/case", status="running", host=socket.gethostname(), pid=os.getpid()
    )

    close_attempt_of_process(tmp_path, 1, None)

    assert read_outcome(run_dir).status == "failed"


def test_other_process_attempt_untouched(tmp_path: Path) -> None:
    run_dir = write_attempt(
        tmp_path, "runs/case", status="running", host=socket.gethostname(), pid=os.getpid() + 1
    )

    close_attempt_of_process(tmp_path, 1, None)

    assert read_outcome(run_dir).status == "running"


def test_no_runs_nothing_to_close(tmp_path: Path) -> None:
    close_attempt_of_process(tmp_path, 1, None)

    assert not (tmp_path / "runs").exists()


# A run deleted to the trash keeps its name: the next run of the case takes the
# next version. ``[simulation] if_exists = "fail"`` takes no new name at all
# when any version of the case is held, live or deleted, and leaves nothing on
# disk. A retry of an unfinished attempt reuses its own directory and gives out
# no name, so ``fail`` lets it through.
AT = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)


def sealed_run(project: Path, name: str) -> Path:
    store = open_run_store(project, name, create_zarr=False)
    seal_completed(store)
    close_sealed_attempt(store.run_dir)
    return store.run_dir


def claim(project: Path, name: str, **kwargs: object):
    return claim_run_directory(project, name, case_id=name, project=project.name, **kwargs)


def live_runs(project: Path) -> list[str]:
    return sorted(entry.name for entry in (project / RUNS_DIRNAME).iterdir())


def test_trashed_name_next_version(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sealed_run(project, "alpha")
    trash_run(project, "runs/alpha", now=datetime.now(UTC))

    taken = claim(project, "alpha")

    assert taken.name == "alpha.v2"
    assert not (project / "runs" / "alpha").exists()


def test_fail_refuses_trashed_name(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sealed_run(project, "alpha")
    trash_run(project, "runs/alpha", now=datetime.now(UTC))

    with pytest.raises(NameTakenError, match="trash:runs/alpha"):
        claim(project, "alpha", if_exists="fail")

    assert live_runs(project) == []


def test_fail_refuses_a_completed_name(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sealed_run(project, "alpha")

    with pytest.raises(NameTakenError, match="runs/alpha"):
        claim(project, "alpha", if_exists="fail")

    assert live_runs(project) == ["alpha"]


def test_fail_takes_a_name_nobody_holds(tmp_path: Path) -> None:
    project = tmp_path / "p"
    (project / "runs").mkdir(parents=True)

    assert claim(project, "beta", if_exists="fail").name == "beta"


def test_fail_lets_an_unfinished_attempt_retry(tmp_path: Path) -> None:
    project = tmp_path / "p"
    first = claim_run(project, "alpha")
    finish_attempt(first.run_dir, status="failed", exit_code=1)

    retry = claim(project, "alpha", if_exists="fail")

    assert retry.run_dir == first.run_dir
    assert retry.attempt == 2
    outcome = read_outcome(first.run_dir)
    assert outcome is not None and outcome.status == "running"


# A version is given by the disk at the reservation, never written by hand. A
# name that carries ``.vN`` reaches only its live directory; the trash, a
# tombstone or a void does not hand it out again.


def test_a_collected_version_is_not_reassigned(tmp_path: Path) -> None:
    reserve_version_dirname(tmp_path, "run", "nancon")
    assert reserve_version_dirname(tmp_path, "run", "nancon").name == "nancon.v2"
    trash_run(tmp_path, "runs/nancon.v2", now=AT)
    freed = gc_trash(tmp_path, older_than=timedelta(0), now=AT + timedelta(days=31))

    assert [tombstone.rel_dir for tombstone in freed] == ["runs/nancon.v2"]
    assert list_trash(tmp_path) == []
    assert live_runs(tmp_path) == ["nancon"]
    assert [t.rel_dir for t in read_tombstones(tmp_path)] == ["runs/nancon.v2"]
    assert reserve_version_dirname(tmp_path, "run", "nancon").name == "nancon.v3"


def test_trashed_version_not_reassigned(tmp_path: Path) -> None:
    reserve_version_dirname(tmp_path, "run", "nancon")
    reserve_version_dirname(tmp_path, "run", "nancon")

    trash_run(tmp_path, "runs/nancon.v2", now=AT)

    assert live_runs(tmp_path) == ["nancon"]
    assert reserve_version_dirname(tmp_path, "run", "nancon").name == "nancon.v3"


def test_collected_bare_name_not_reassigned(tmp_path: Path) -> None:
    reserve_version_dirname(tmp_path, "run", "nancon")
    trash_run(tmp_path, "runs/nancon", now=AT)
    gc_trash(tmp_path, older_than=timedelta(0), now=AT)

    assert reserve_version_dirname(tmp_path, "run", "nancon").name == "nancon.v2"


def test_trashed_versioned_name_refused(tmp_path: Path) -> None:
    sealed_run(tmp_path, "a")
    assert sealed_run(tmp_path, "a").name == "a.v2"
    trash_run(tmp_path, "runs/a.v2", now=AT)
    assert [entry.rel_dir for entry in list_trash(tmp_path)] == ["runs/a.v2"]

    with pytest.raises(NameTakenError, match=r"trash:runs/a\.v2.*name the case 'a'"):
        claim(tmp_path, "a.v2")

    assert live_runs(tmp_path) == ["a"]


def test_tombstone_versioned_name_refused(tmp_path: Path) -> None:
    sealed_run(tmp_path, "nancon")
    sealed_run(tmp_path, "nancon")
    trash_run(tmp_path, "runs/nancon", now=AT)
    trash_run(tmp_path, "runs/nancon.v2", now=AT)
    gc_trash(tmp_path, older_than=timedelta(0), now=AT)
    assert "runs/nancon.v2" in [t.rel_dir for t in read_tombstones(tmp_path)]

    with pytest.raises(NameTakenError, match=r"tombstone:runs/nancon\.v2.*'nancon'"):
        claim(tmp_path, "nancon.v2")

    assert live_runs(tmp_path) == []


def test_versioned_name_retries_directory(tmp_path: Path) -> None:
    sealed_run(tmp_path, "a")
    second = claim_run(tmp_path, "a")
    finish_attempt(second.run_dir, status="failed", exit_code=1)

    retry = claim(tmp_path, "a.v2")

    assert retry.run_dir == second.run_dir
    assert retry.attempt == 2


def test_completed_versioned_name_next(tmp_path: Path) -> None:
    for _ in range(3):
        sealed_run(tmp_path, "a")
    trash_run(tmp_path, "runs/a.v3", now=AT)

    assert claim(tmp_path, "a.v2").name == "a.v4"


def test_simulation_name_has_no_version() -> None:
    with pytest.raises(ValidationError, match="write name = 'a'"):
        SimulationConfig(name="a.v2")

    assert SimulationConfig(name="a.vintage").name == "a.vintage"


# ``hmp catalog delete x --now`` once purged the live ``x.v2`` because a bare
# ``x`` meant "the latest version". Now ``x`` is ``runs/x`` exactly, a bare name
# with other versions is refused with the list, and a trashed directory is
# purged only by the trash verbs.


def hmp(monkeypatch, *argv: str) -> int:
    main = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", ["hmp", *argv])
    try:
        main.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def project_with_runs(tmp_path: Path, *names: str) -> Path:
    project = tmp_path / "p"
    project.mkdir()
    (project / "project.toml").write_text('[site]\nname = "p"\n', encoding="utf-8")
    for name in names:
        (project / "runs" / name).mkdir(parents=True)
    return project


def test_purge_bare_name_refused(tmp_path: Path, monkeypatch) -> None:
    project = project_with_runs(tmp_path, "x", "x.v2")

    code = hmp(monkeypatch, "catalog", "delete", "x", "--now", "-y", "-w", str(project))

    assert code == EXIT_AMBIGUOUS_REFERENCE
    assert (project / "runs" / "x").is_dir()
    assert (project / "runs" / "x.v2").is_dir()


def test_purge_by_full_path(tmp_path: Path, monkeypatch) -> None:
    project = project_with_runs(tmp_path, "x", "x.v2")

    code = hmp(monkeypatch, "catalog", "delete", "runs/x", "--now", "-y", "-w", str(project))

    assert code == 0
    assert not (project / "runs" / "x").exists()
    assert (project / "runs" / "x.v2").is_dir()
    assert [tombstone.rel_dir for tombstone in read_tombstones(project)] == ["runs/x"]
