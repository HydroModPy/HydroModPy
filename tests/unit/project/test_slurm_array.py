"""``write_slurm_array`` writes a frozen SLURM job for the current plan.

``jobs/<stamp>-slurm/`` holds ``prepare.sh``, ``array.sh`` and ``cases.txt``:
line N of ``cases.txt`` is the case task N runs, in the order of the plan.
The scripts carry the scheduler warning, the cpus of a case, the node scratch
and the trap; ``bash -n`` accepts them. A job directory is written once, from
a current plan only.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pytest

from hydromodpy.core.exceptions import ConfigError, JobUsageError
from hydromodpy.project.launch.journal import case_for_task, read_case_list
from hydromodpy.project.launch.slurm import TERM_GRACE_S, walltime_seconds, write_slurm_array
from hydromodpy.results.plan_store import Plan, PlanCase, StoredPlan, read_plan, write_plan

STAMP = "20261020-143000"
PLAN_HASH = "0123abcd0123abcd"
PROJECT_TOML = """\
[sites]
table = "sites.csv"

[sites.recipes]
base = "base.toml"

[sites.run]
threads_per_case = {threads}
prepare_parallel = {prepare}
"""


def planned_project(
    root: Path,
    *,
    cases: tuple[str, ...] = ("J001-base", "J002-base", "J003-calage"),
    calibration_parallel: dict[str, int] | None = None,
    threads: int = 2,
    prepare: int = 3,
) -> StoredPlan:
    """Write a ``[sites]`` project and its current plan; return the plan."""
    root.mkdir(parents=True, exist_ok=True)
    project_toml = root / "project.toml"
    project_toml.write_text(PROJECT_TOML.format(threads=threads, prepare=prepare))
    parallel = calibration_parallel or {}
    tomls: dict[str, str] = {}
    for case_id in cases:
        site = case_id.split("-")[0]
        text = f'[site]\nname = "{site}"\n'
        if case_id in parallel:
            text += f"\n[calibration]\nparallel = {parallel[case_id]}\n"
        tomls[case_id] = text
    plan = Plan(
        plan_hash=PLAN_HASH,
        hydromodpy_version="test",
        created_at=datetime(2026, 10, 20, 14, 0, tzinfo=UTC),
        fingerprints={"project.toml": hashlib.sha256(project_toml.read_bytes()).hexdigest()},
        n_cases=len(cases),
    )
    plan_cases = [
        PlanCase(
            case_id=case_id,
            site=case_id.split("-")[0],
            recipe=case_id.split("-")[1],
            config_hash=f"hash-{case_id}",
            config_path=f"{case_id}.toml",
        )
        for case_id in cases
    ]
    sites = pa.table({"site": sorted({c.split("-")[0] for c in cases})})
    write_plan(root, plan, sites, plan_cases, tomls)
    return read_plan(root)


def _directive(text: str, key: str) -> str:
    match = re.search(rf"^#SBATCH --{key}=(.+)$", text, flags=re.MULTILINE)
    assert match is not None, f"no --{key} directive"
    return match.group(1)


def test_the_job_holds_two_scripts_and_the_cases_of_the_plan(tmp_path: Path) -> None:
    root = tmp_path / "bretagne"
    stored = planned_project(root)

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


@pytest.mark.allow_subprocess
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_both_scripts_parse_under_bash_and_are_executable(tmp_path: Path) -> None:
    root = tmp_path / "p"
    planned_project(root)
    job = write_slurm_array(root, stamp=STAMP, partition="normal", walltime="12:00:00")

    for script in (job.prepare_sh, job.array_sh):
        done = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        assert script.stat().st_mode & 0o111
        assert "{{" not in script.read_text()


def test_the_array_script_carries_the_warning_the_cpus_the_scratch_and_the_trap(
    tmp_path: Path,
) -> None:
    root = tmp_path / "p"
    planned_project(root, threads=2)
    job = write_slurm_array(root, stamp=STAMP)
    text = job.array_sh.read_text()

    assert _directive(text, "signal") == f"B:TERM@{TERM_GRACE_S}"
    assert _directive(text, "cpus-per-task") == "2"
    assert _directive(text, "array") == "1-3"
    assert _directive(text, "chdir") == str(root)
    assert _directive(text, "output") == f"{job.directory}/logs/array-%A_%a.out"
    assert 'export HMP_SCRATCH_ROOT="$SLURM_TMPDIR"' in text
    assert "trap forward_term TERM" in text
    assert 'CASE_TOML="$(hmp project case "$JOB" "$SLURM_ARRAY_TASK_ID")"' in text
    assert "task-flags \\\n    --phase solve" in text
    assert 'hmp run "$CASE_TOML" ${RUN_FLAGS[@]+"${RUN_FLAGS[@]}"} &' in text
    assert "export HMP_THREADS_PER_CASE=2" in text
    assert "export HMP_LAUNCHED_CASE=slurm" in text
    assert "-m hydromodpy.project.launch.slurm finish-task" in text
    assert "--partition" not in text and "--time" not in text


def test_the_prepare_script_throttles_and_writes_the_lock_once(tmp_path: Path) -> None:
    root = tmp_path / "p"
    planned_project(root, threads=2, prepare=3)
    job = write_slurm_array(root, stamp=STAMP)
    text = job.prepare_sh.read_text()

    assert _directive(text, "array") == "1-3%3"
    assert _directive(text, "cpus-per-task") == "2"
    assert _directive(text, "signal") == f"B:TERM@{TERM_GRACE_S}"
    assert "task-flags \\\n    --phase prepare" in text
    assert "--until data" not in text and "--resume" not in text
    assert "-m hydromodpy.project.launch.slurm write-lock" in text
    assert "hmp dev lock" not in text
    assert "export HMP_THREADS_PER_CASE=2" in text
    assert "HMP_SCRATCH_ROOT" not in text
    assert (job.directory / "prepared").is_dir() and (job.directory / "logs").is_dir()


def test_a_calibration_case_sizes_the_cpus_of_every_task(tmp_path: Path) -> None:
    root = tmp_path / "p"
    planned_project(root, threads=2, calibration_parallel={"J003-calage": 5})

    job = write_slurm_array(root, stamp=STAMP)

    assert job.max_solves == 5 and job.cpus_per_task == 10
    assert _directive(job.array_sh.read_text(), "cpus-per-task") == "10"
    assert _directive(job.prepare_sh.read_text(), "cpus-per-task") == "2"


def test_options_reach_the_directives(tmp_path: Path) -> None:
    root = tmp_path / "p"
    planned_project(root, threads=2, prepare=3)

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


def test_a_job_directory_is_written_once(tmp_path: Path) -> None:
    root = tmp_path / "p"
    planned_project(root)
    job = write_slurm_array(root, stamp=STAMP)
    before = job.cases_txt.read_bytes()

    with pytest.raises(JobUsageError, match="written once"):
        write_slurm_array(root, stamp=STAMP)

    assert job.cases_txt.read_bytes() == before
    assert not [p for p in (root / "jobs").iterdir() if p.name.startswith(".staging")]


def test_a_later_plan_leaves_the_cases_of_a_waiting_job_alone(tmp_path: Path) -> None:
    root = tmp_path / "p"
    planned_project(root)
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


def test_a_plan_older_than_its_project_file_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "p"
    planned_project(root)
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
    ],
)
def test_invalid_options_are_refused(tmp_path: Path, kwargs: dict, message: str) -> None:
    root = tmp_path / "p"
    planned_project(root)

    with pytest.raises(ConfigError, match=message):
        write_slurm_array(root, stamp=STAMP, **kwargs)
    assert not (root / "jobs").exists()


def test_a_stamp_and_a_project_path_are_checked(tmp_path: Path) -> None:
    root = tmp_path / "p"
    planned_project(root)
    with pytest.raises(JobUsageError, match="stamp"):
        write_slurm_array(root, stamp="today")

    spaced = tmp_path / "with space"
    planned_project(spaced)
    with pytest.raises(ConfigError, match="#SBATCH"):
        write_slurm_array(spaced, stamp=STAMP)


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
)
def test_walltime_forms(text: str, seconds: int) -> None:
    assert walltime_seconds(text) == seconds


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
