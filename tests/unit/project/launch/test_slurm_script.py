"""The scripts and directives of a SLURM job, and the trap of a task.

The scripts carry the scheduler warning (seconds before the kill), the cpus of
a case and the node scratch; ``bash -n`` accepts them. Bash runs the array
script as a node would, with a stand-in interpreter in ``HMP_PYTHON``. A worker
that crashes is closed as failed by the trap, one that wrote its exit is left
alone, and the task that completes the prepare phase writes the lock.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hydromodpy.project.launch.slurm import write_slurm_array
from hydromodpy.project.launch.slurm_script import TERM_GRACE_S, walltime_seconds, worker_block
from hydromodpy.results.outcome import read_outcome
from tests.unit.project.launch._helpers import STAMP, planned_project

CASES = ("j001-base", "j002-base", "j003-calage")
"""The cases of the plan, named as the plan names them: folded to a run name."""


def _planned(root: Path, **kwargs):
    return planned_project(root, cases=CASES, **kwargs)


def assert_bash_accepts(script: Path) -> None:
    done = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def _directive(text: str, key: str) -> str:
    match = re.search(rf"^#SBATCH --{key}=(.+)$", text, flags=re.MULTILINE)
    assert match is not None, f"no --{key} directive"
    return match.group(1)


@pytest.mark.allow_subprocess
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_scripts_parse_under_bash(tmp_path: Path) -> None:
    root = tmp_path / "p"
    _planned(root)
    job = write_slurm_array(root, stamp=STAMP, partition="normal", walltime="12:00:00")

    for script in (job.prepare_sh, job.array_sh):
        assert_bash_accepts(script)
        assert script.stat().st_mode & 0o111
        assert "{{" not in script.read_text()


def test_array_script_directives(
    tmp_path: Path,
) -> None:
    root = tmp_path / "p"
    _planned(root, threads=2)
    job = write_slurm_array(root, stamp=STAMP)
    text = job.array_sh.read_text()

    assert _directive(text, "signal") == f"B:TERM@{TERM_GRACE_S}"
    assert _directive(text, "cpus-per-task") == "2"
    assert _directive(text, "array") == "1-3"
    assert _directive(text, "chdir") == str(root)
    assert _directive(text, "output") == f"{job.directory}/logs/array-%A_%a.out"
    assert 'export HMP_SCRATCH_ROOT="$SLURM_TMPDIR"' in text
    assert "trap forward_term TERM" in text
    assert (
        'CASE_TOML="$("$HMP_PYTHON" -m hydromodpy campaign case "$JOB" "$SLURM_ARRAY_TASK_ID")"'
        in text
    )
    assert "task-flags \\\n    --phase solve" in text
    assert (
        '"$HMP_PYTHON" -m hydromodpy run "$CASE_TOML"'
        ' ${RUN_FLAGS[@]+"${RUN_FLAGS[@]}"}'
        ' ${ENVIRONMENT_FLAGS[@]+"${ENVIRONMENT_FLAGS[@]}"} &' in text
    )
    assert not re.search(r"(^|\$\()\s*hmp ", text, re.M)
    assert "export HMP_THREADS_PER_CASE=2" in text
    assert "export HMP_LAUNCHED_CASE=slurm" in text
    assert "-m hydromodpy.project.launch.slurm finish-task" in text
    assert "--partition" not in text and "--time" not in text


@pytest.mark.allow_subprocess
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_environment_flags_in_tasks(tmp_path: Path) -> None:
    root = tmp_path / "p"
    _planned(root, threads=2)
    job = write_slurm_array(
        root,
        stamp=STAMP,
        environment_flags=[
            "--credentials",
            "c.toml",
            "--allow-host",
            "a.b",
            "--max-download-bytes",
            "10",
        ],
    )

    for script in (job.prepare_sh, job.array_sh):
        assert_bash_accepts(script)
        text = script.read_text()
        assert "ENVIRONMENT_FLAGS=(--credentials c.toml --allow-host a.b" in text
        assert "--max-download-bytes 10)" in text

    plain_job = write_slurm_array(root, stamp="19991231-235959")
    plain = plain_job.array_sh.read_text()
    assert "ENVIRONMENT_FLAGS=()" in plain
    assert "--credentials" not in plain
    assert (
        '"$HMP_PYTHON" -m hydromodpy run "$CASE_TOML"'
        ' ${RUN_FLAGS[@]+"${RUN_FLAGS[@]}"}'
        ' ${ENVIRONMENT_FLAGS[@]+"${ENVIRONMENT_FLAGS[@]}"} &' in plain
    )


@pytest.mark.allow_subprocess
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_shell_special_flag_is_quoted(tmp_path: Path) -> None:
    root = tmp_path / "p"
    _planned(root, threads=2)
    tricky = 'a "b" $HOME `id`'
    job = write_slurm_array(root, stamp=STAMP, environment_flags=["--credentials", tricky])

    assert_bash_accepts(job.array_sh)
    text = job.array_sh.read_text()
    assert f"ENVIRONMENT_FLAGS=(--credentials {shlex.quote(tricky)})" in text
    # The run line keeps one flag: the quoted value crosses the render whole.
    assert '${ENVIRONMENT_FLAGS[@]+"${ENVIRONMENT_FLAGS[@]}"} &' in text


def test_prepare_script_directives(tmp_path: Path) -> None:
    root = tmp_path / "p"
    _planned(root, threads=2, prepare=3)
    job = write_slurm_array(root, stamp=STAMP)
    text = job.prepare_sh.read_text()

    assert _directive(text, "array") == "1-3%3"
    assert _directive(text, "cpus-per-task") == "2"
    assert _directive(text, "signal") == f"B:TERM@{TERM_GRACE_S}"
    assert "task-flags \\\n    --phase prepare" in text
    assert "--until data" not in text and "--resume" not in text
    assert "-m hydromodpy.project.launch.slurm write-lock" in text
    assert not re.search(r"(^|\$\()\s*hmp ", text, re.M)
    assert '"$HMP_PYTHON" -m hydromodpy run "$CASE_TOML"' in text
    assert "hmp lock" not in text
    assert "export HMP_THREADS_PER_CASE=2" in text
    assert "HMP_SCRATCH_ROOT" not in text
    assert (job.directory / "prepared").is_dir() and (job.directory / "logs").is_dir()


def test_calibration_sizes_task_cpus(tmp_path: Path) -> None:
    root = tmp_path / "p"
    _planned(root, threads=2, calibration_parallel={"j003-calage": 5})

    job = write_slurm_array(root, stamp=STAMP)

    assert job.max_solves == 5 and job.cpus_per_task == 10
    assert _directive(job.array_sh.read_text(), "cpus-per-task") == "10"
    assert _directive(job.prepare_sh.read_text(), "cpus-per-task") == "2"


def test_options_reach_the_directives(tmp_path: Path) -> None:
    root = tmp_path / "p"
    _planned(root, threads=2, prepare=3)

    job = write_slurm_array(
        root,
        stamp=STAMP,
        partition="normal",
        walltime="1-00:00:00",
        threads_per_case=4,
        prepare_parallel=1,
    )

    for script in (job.prepare_sh, job.array_sh):
        text = script.read_text()
        assert _directive(text, "partition") == "normal"
        assert _directive(text, "time") == "1-00:00:00"
    assert _directive(job.array_sh.read_text(), "cpus-per-task") == "4"
    assert _directive(job.prepare_sh.read_text(), "array") == "1-3%1"


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("30", 1800),
        ("30:15", 1815),
        ("12:00:00", 43200),
        ("2-6", 2 * 86400 + 6 * 3600),
        ("1-02:30", 86400 + 2 * 3600 + 30 * 60),
        ("1-00:00:05", 86405),
    ],
    ids=[
        "minutes",
        "minutes:seconds",
        "hours:minutes:seconds",
        "days-hours",
        "days-hours:minutes",
        "days-time",
    ],
)
def test_walltime_forms(text: str, seconds: int) -> None:
    assert walltime_seconds(text) == seconds


@pytest.mark.allow_subprocess
def test_task_strips_shell_overrides() -> None:
    env = {"PATH": "/usr/bin:/bin", "HMP_SET_a__b": "1"}
    script = worker_block("solve").split('cd "$PROJECT_ROOT"')[0]
    probe = script + '\nenv | grep -c "^HMP_" || true\n'
    out = subprocess.run(["bash", "-c", probe], env=env, capture_output=True, text=True)
    assert out.stdout.strip() == "0"


FAKE_HMP = """\
#!{python}
import os
import signal
import sys
import time
from pathlib import Path

args = sys.argv[1:]
root = Path.cwd()
if args[:2] == ["campaign", "case"]:
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
    _planned(root)
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


@pytest.mark.allow_subprocess
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_crashed_worker_closed_by_trap(tmp_path: Path) -> None:
    root, proc = _task(tmp_path, "crash")
    assert proc.wait(timeout=50) == 137

    run_dir = root / "runs" / "j001-base"
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


@pytest.mark.allow_subprocess
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_term_warning_reaches_worker(tmp_path: Path) -> None:
    root, proc = _task(tmp_path, "sleep")
    deadline = time.monotonic() + 40
    while not (tmp_path / "ready").exists():
        assert proc.poll() is None, "the task ended before its worker started"
        assert time.monotonic() < deadline, "the worker never started"
        time.sleep(0.1)

    proc.send_signal(signal.SIGTERM)

    assert proc.wait(timeout=40) == 128 + signal.SIGTERM
    outcome = read_outcome(root / "runs" / "j001-base")
    assert outcome is not None
    assert outcome.status == "failed" and outcome.written_by == "trap"
    assert outcome.signal == signal.SIGTERM


@pytest.mark.allow_subprocess
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_worker_exit_left_alone(tmp_path: Path) -> None:
    root, proc = _task(tmp_path, "finish")
    assert proc.wait(timeout=50) == 15

    run_dir = root / "runs" / "j001-base"
    outcome = read_outcome(run_dir)
    assert outcome is not None
    assert outcome.written_by == "worker" and outcome.exit_code == 15
    assert outcome.error is not None and outcome.error.message == "no converge"
    assert (run_dir / "logs" / "job-42_1.out").is_file()


@pytest.mark.allow_subprocess
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_last_prepare_task_writes_lock(tmp_path: Path) -> None:
    root, job_dir = _job(tmp_path)
    for task in ("2", "3"):
        (job_dir / "prepared" / task).touch()

    assert _launch(tmp_path, job_dir, "ok", "prepare.sh").wait(timeout=50) == 0

    assert (job_dir / "prepared" / "1").is_file()
    assert (root / "hydromodpy.lock").read_text() == "pinned\n"
    log = (job_dir / "logs" / "prepare-42_1.out").read_text()
    assert "worker started --until load_data" in log


@pytest.mark.allow_subprocess
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_other_prepare_tasks_write_no_lock(
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
