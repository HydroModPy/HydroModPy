"""``scheduler_states`` reads ``sacct`` for the cases of the array jobs, when it is there.

A stand-in ``sacct`` on the PATH answers as SLURM does with ``--parsable2``.
Each task maps to the case of its line in the frozen ``cases.txt``; a task
submitted again takes its latest job id; a pending range names every task
it holds; a terminal state is the scheduler's proof that the task ended."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hydromodpy.project.launch.sacct import scheduler_states
from hydromodpy.project.launch.slurm import write_slurm_array
from tests.unit.project.launch._helpers import STAMP, planned_project

pytestmark = pytest.mark.allow_subprocess


SACCT_OUTPUT = """\
41_1|hmp-p-20261020-143000|TIMEOUT|0:15
42_1|hmp-p-20261020-143000|COMPLETED|0:0
42_2|hmp-p-20261020-143000|CANCELLED by 1000|0:0
42_[3]|hmp-p-20261020-143000|PENDING|0:0
"""


def _fake_sacct(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str) -> Path:
    folder = tmp_path / "bin"
    folder.mkdir()
    calls = tmp_path / "sacct-calls.txt"
    script = folder / "sacct"
    script.write_text(f"#!/bin/sh\necho \"$@\" >> {calls}\ncat <<'EOF'\n{output}EOF\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    return calls


def test_each_case_takes_the_state_of_its_latest_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "p"
    planned_project(root)
    job = write_slurm_array(root, stamp=STAMP)
    calls = _fake_sacct(tmp_path, monkeypatch, SACCT_OUTPUT)

    states = scheduler_states(root)

    assert set(states) == {"J001-base", "J002-base", "J003-calage"}
    assert states["J001-base"].job_id == "42_1" and states["J001-base"].state == "COMPLETED"
    assert states["J002-base"].state == "CANCELLED" and states["J002-base"].finished
    assert states["J003-calage"].state == "PENDING" and not states["J003-calage"].finished
    call = calls.read_text()
    assert f"--name={job.job_name}" in call
    assert "--starttime=2026-10-19" in call and "--parsable2" in call


def test_a_pending_range_names_every_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "p"
    planned_project(root)
    write_slurm_array(root, stamp=STAMP)
    _fake_sacct(tmp_path, monkeypatch, "50_[1-3%2]|hmp-p-20261020-143000|PENDING|0:0\n")

    states = scheduler_states(root)

    assert {case: row.job_id for case, row in states.items()} == {
        "J001-base": "50_1",
        "J002-base": "50_2",
        "J003-calage": "50_3",
    }


def test_a_later_job_directory_wins_for_its_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "p"
    planned_project(root)
    write_slurm_array(root, stamp=STAMP)
    write_slurm_array(root, stamp="20261021-090000")
    folder = tmp_path / "bin"
    folder.mkdir()
    script = folder / "sacct"
    script.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        "  *20261021-090000*) echo '70_1|later|FAILED|1:0' ;;\n"
        "  *) echo '60_1|earlier|COMPLETED|0:0' ;;\n"
        "esac\n"
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")

    states = scheduler_states(root)

    assert states["J001-base"].state == "FAILED"
    assert states["J001-base"].job_id == "70_1"


def test_without_sacct_the_scheduler_says_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "p"
    planned_project(root)
    write_slurm_array(root, stamp=STAMP)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    assert scheduler_states(root) == {}


def test_a_failing_sacct_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "p"
    planned_project(root)
    write_slurm_array(root, stamp=STAMP)
    folder = tmp_path / "bin"
    folder.mkdir()
    script = folder / "sacct"
    script.write_text("#!/bin/sh\necho 'slurmdbd unreachable' >&2\nexit 1\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")

    assert scheduler_states(root) == {}
