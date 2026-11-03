"""The trap of a SLURM task writes ``failed`` when the worker left ``running`` behind.

The array script is run by bash as a node would run it, with SLURM's
variables set and a stand-in interpreter in ``HMP_PYTHON``, with no ``hmp`` on
the PATH: the scripts reach the CLI through ``$HMP_PYTHON -m hydromodpy``, and
the stand-in sends that to a stand-in ``hmp`` that claims the run directory
like a worker, then crashes, is terminated through the shell, or ends
properly. The flags it receives come from the real ``task-flags`` step; only
``write-lock`` goes through the stand-in too. After it, the trap step closes the directory: ``failed``
with the exit code, the signal, the log tail and ``written_by = "trap"``
when the worker said nothing, nothing at all when it wrote its own exit.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.project.launch.slurm import finish_task, write_slurm_array
from hydromodpy.results.outcome import Outcome, read_outcome, write_outcome
from hydromodpy.results.session.descriptor import read_session, write_session
from hydromodpy.results.storage.attempt import claim_run_directory
from tests._helpers.session_documents import session_descriptor
from tests.unit.project.test_slurm_array import STAMP, planned_project

pytestmark = [
    pytest.mark.allow_subprocess,
    pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed"),
]

FAKE_HMP = """\
#!{python}
import os
import signal
import sys
import time
from pathlib import Path

args = sys.argv[1:]
root = Path.cwd()
if args[:2] == ["project", "case"]:
    lines = (root / "jobs" / args[2] / "cases.txt").read_text().splitlines()
    print(root / lines[int(args[3]) - 1])
    sys.exit(0)
if args[0] != "run":
    sys.exit(2)

from hydromodpy.results.storage.attempt import claim_run_directory, finish_attempt

case = Path(args[1]).stem
claim = claim_run_directory(root, case, case_id=case, project=root.name)
signal.signal(signal.SIGTERM, signal.SIG_DFL)
print("worker started", " ".join(args[2:]), flush=True)
print(
    "budget",
    os.environ.get("HMP_THREADS_PER_CASE"),
    os.environ.get("HMP_LAUNCHED_CASE"),
    flush=True,
)
mode = os.environ["FAKE_WORKER"]
if mode == "crash":
    os._exit(137)
if mode == "sleep":
    Path(os.environ["FAKE_READY"]).touch()
    time.sleep(120)
if mode == "ok":
    finish_attempt(claim.run_dir, status="completed", exit_code=0)
    sys.exit(0)
if mode == "finish":
    finish_attempt(claim.run_dir, status="failed", exit_code=15, error=RuntimeError("no converge"))
    sys.exit(15)
"""


FAKE_PYTHON = """\
#!/usr/bin/env bash
if [ "$3" = "write-lock" ]; then
    echo "pinned" > "$PWD/hydromodpy.lock"
    exit 0
fi
if [ "$1" = "-m" ] && [ "$2" = "hydromodpy" ]; then
    shift 2
    exec {hmp} "$@"
fi
exec {python} "$@"
"""


def _bin(tmp_path: Path) -> Path:
    folder = tmp_path / "bin"
    folder.mkdir()
    hmp = folder / "worker-hmp"
    hmp.write_text(FAKE_HMP.format(python=sys.executable))
    hmp.chmod(0o755)
    python = folder / "python"
    python.write_text(FAKE_PYTHON.format(python=sys.executable, hmp=hmp))
    python.chmod(0o755)
    return folder


def _env(tmp_path: Path, mode: str) -> dict[str, str]:
    env = dict(os.environ)
    folder = _bin(tmp_path)
    env.update(
        HMP_PYTHON=str(folder / "python"),
        SLURM_ARRAY_JOB_ID="42",
        SLURM_ARRAY_TASK_ID="1",
        SLURM_TMPDIR=str(tmp_path / "node-tmp"),
        FAKE_WORKER=mode,
        FAKE_READY=str(tmp_path / "ready"),
    )
    env.pop("HMP_SCRATCH_ROOT", None)
    return env


def _job(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "p"
    planned_project(root)
    return root, write_slurm_array(root, stamp=STAMP).directory


def _launch(tmp_path: Path, job_dir: Path, mode: str, script: str) -> subprocess.Popen:
    prefix = script.removesuffix(".sh")
    log = job_dir / "logs" / f"{prefix}-42_1.out"
    with log.open("w") as handle:
        return subprocess.Popen(
            ["bash", str(job_dir / script)],
            cwd=tmp_path,
            env=_env(tmp_path, mode),
            stdout=handle,
            stderr=subprocess.STDOUT,
        )


def _task(tmp_path: Path, mode: str) -> tuple[Path, subprocess.Popen]:
    root, job_dir = _job(tmp_path)
    (root / "hydromodpy.lock").write_text("pinned\n")
    return root, _launch(tmp_path, job_dir, mode, "array.sh")


def test_a_crashed_worker_is_closed_as_failed_by_the_trap(tmp_path: Path) -> None:
    root, proc = _task(tmp_path, "crash")
    assert proc.wait(timeout=50) == 137

    run_dir = root / "runs" / "J001-base"
    outcome = read_outcome(run_dir)
    assert outcome is not None
    assert outcome.status == "failed"
    assert outcome.written_by == "trap"
    assert outcome.exit_code == 137 and outcome.signal == 9
    assert outcome.scheduler_job_id == "42_1"
    assert any(line == "worker started --frozen" for line in outcome.log_tail)
    assert "budget 2 slurm" in outcome.log_tail
    copied = run_dir / "logs" / "job-42_1.out"
    assert "worker started" in copied.read_text()
    assert (run_dir / "README.md").is_file()


def test_the_scheduler_warning_reaches_the_worker_through_the_shell(tmp_path: Path) -> None:
    root, proc = _task(tmp_path, "sleep")
    deadline = time.monotonic() + 40
    while not (tmp_path / "ready").exists():
        assert proc.poll() is None, "the task ended before its worker started"
        assert time.monotonic() < deadline, "the worker never started"
        time.sleep(0.1)

    proc.send_signal(signal.SIGTERM)

    assert proc.wait(timeout=40) == 128 + signal.SIGTERM
    outcome = read_outcome(root / "runs" / "J001-base")
    assert outcome is not None
    assert outcome.status == "failed" and outcome.written_by == "trap"
    assert outcome.signal == signal.SIGTERM


def test_a_worker_that_wrote_its_exit_is_left_alone(tmp_path: Path) -> None:
    root, proc = _task(tmp_path, "finish")
    assert proc.wait(timeout=50) == 15

    run_dir = root / "runs" / "J001-base"
    outcome = read_outcome(run_dir)
    assert outcome is not None
    assert outcome.written_by == "worker" and outcome.exit_code == 15
    assert outcome.error is not None and outcome.error.message == "no converge"
    assert (run_dir / "logs" / "job-42_1.out").is_file()


def test_the_task_that_completes_the_prepare_phase_writes_the_lock(tmp_path: Path) -> None:
    root, job_dir = _job(tmp_path)
    for task in ("2", "3"):
        (job_dir / "prepared" / task).touch()

    assert _launch(tmp_path, job_dir, "ok", "prepare.sh").wait(timeout=50) == 0

    assert (job_dir / "prepared" / "1").is_file()
    assert (root / "hydromodpy.lock").read_text() == "pinned\n"
    log = (job_dir / "logs" / "prepare-42_1.out").read_text()
    assert "worker started --until load_data" in log


def test_a_prepare_task_that_is_not_the_last_or_that_failed_writes_no_lock(
    tmp_path: Path,
) -> None:
    root, job_dir = _job(tmp_path / "first")
    assert _launch(tmp_path / "first", job_dir, "ok", "prepare.sh").wait(timeout=50) == 0
    assert (job_dir / "prepared" / "1").is_file()
    assert not (root / "hydromodpy.lock").exists()

    root, job_dir = _job(tmp_path / "failed")
    for task in ("2", "3"):
        (job_dir / "prepared" / task).touch()
    assert _launch(tmp_path / "failed", job_dir, "finish", "prepare.sh").wait(timeout=50) == 15
    assert not (job_dir / "prepared" / "1").exists()
    assert not (root / "hydromodpy.lock").exists()


def _claimed(tmp_path: Path, *, pid: int, host: str | None = None) -> tuple[Path, Path]:
    root = tmp_path / "p"
    stored = planned_project(root)
    claim = claim_run_directory(root, "J001-base", case_id="J001-base", project="p")
    outcome = read_outcome(claim.run_dir)
    assert outcome is not None
    update: dict[str, object] = {"pid": pid}
    if host is not None:
        update["host"] = host
    write_outcome(claim.run_dir, outcome.model_copy(update=update))
    return root, stored.directory / "J001-base.toml"


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_finish_task_reads_the_signal_and_the_tail_of_the_log(tmp_path: Path) -> None:
    root, case_toml = _claimed(tmp_path, pid=_dead_pid())
    log = tmp_path / "task.out"
    log.write_text("".join(f"line {i}\n" for i in range(100)))

    outcome = finish_task(root, case_toml, exit_code=143, log_path=log, job_id="7_1")

    assert outcome is not None and outcome.signal == 15 and outcome.exit_code == 143
    assert outcome.log_tail[-1] == "line 99" and len(outcome.log_tail) == 40
    assert outcome.error is not None and "without writing its outcome" in outcome.error.message


def test_finish_task_leaves_a_live_or_foreign_worker_alone(tmp_path: Path) -> None:
    root, case_toml = _claimed(tmp_path / "alive", pid=os.getpid())
    assert finish_task(root, case_toml, exit_code=1) is None
    outcome = read_outcome(root / "runs" / "J001-base")
    assert outcome is not None and outcome.status == "running"

    root, case_toml = _claimed(
        tmp_path / "foreign", pid=_dead_pid(), host="not-" + socket.gethostname()
    )
    assert finish_task(root, case_toml, exit_code=1) is None
    outcome = read_outcome(root / "runs" / "J001-base")
    assert outcome is not None and outcome.status == "running"


def test_finish_task_without_a_run_directory_writes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "p"
    stored = planned_project(root)

    assert finish_task(root, stored.directory / "J001-base.toml", exit_code=2) is None
    assert not (root / "runs").exists()


def test_a_calibration_session_left_running_is_closed_too(tmp_path: Path) -> None:
    root = tmp_path / "p"
    stored = planned_project(root)
    session = root / "sessions" / "J003-calage"
    session.mkdir(parents=True)
    started = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
    write_session(
        session,
        session_descriptor(
            "J003-calage",
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
            case_id="J003-calage",
            attempt=1,
            attempt_id="a1",
            status="running",
            written_by="worker",
            started_at=started,
            host=socket.gethostname(),
            pid=_dead_pid(),
        ),
    )
    log = tmp_path / "task.out"
    log.write_text("trial 12 diverged\n")

    outcome = finish_task(
        root, stored.directory / "J003-calage.toml", exit_code=137, log_path=log, job_id="9_3"
    )

    assert outcome is not None and outcome.written_by == "trap" and outcome.signal == 9
    assert read_session(session).status == "failed"
    on_disk = read_outcome(session)
    assert on_disk is not None and on_disk.status == "failed"
    assert on_disk.scheduler_job_id == "9_3" and on_disk.log_tail == ["trial 12 diverged"]
    assert (session / "logs" / "job-9_3.out").is_file()
    assert not (session / "README.md").exists()
