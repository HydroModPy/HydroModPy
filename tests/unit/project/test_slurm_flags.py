"""A SLURM task runs ``hmp run`` with the flags the local launcher would pick.

The prepare phase stops after ``load_data`` (a calibration case as a
simulation); the solve takes ``--frozen`` when the lock exists and
``--resume <case>`` only on a simulation left unfinished. The flags are
parsed by the real ``hmp run`` parser and the ``--until`` value is resolved
against the real pipeline steps, so a flag the CLI refuses fails here.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from hydromodpy.cli.commands import run as run_command
from hydromodpy.core.exceptions import JobUsageError
from hydromodpy.project.launch import slurm
from hydromodpy.project.launch.slurm import task_flags, write_lock
from hydromodpy.project.runner import _model_phase_index, _resolve_step_index
from hydromodpy.results.storage.attempt import claim_run_directory, finish_attempt
from hydromodpy.workflow.orchestrator import standard_steps
from tests.unit.project.test_slurm_array import planned_project

CALIBRATION = "J003-calage"


def _project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "p"
    stored = planned_project(root, calibration_parallel={CALIBRATION: 2})
    return root, stored.directory


def _parsed(case: Path, flags: list[str]) -> argparse.Namespace:
    subparsers = argparse.ArgumentParser(prog="hmp").add_subparsers()
    return run_command.register(subparsers).parse_args([str(case), *flags])


def test_the_prepare_phase_stops_after_load_data(tmp_path: Path) -> None:
    root, plan = _project(tmp_path)

    flags = task_flags(root, plan / "J001-base.toml", phase="prepare")

    assert flags == ["--until", "load_data"]
    args = _parsed(plan / "J001-base.toml", flags)
    steps = standard_steps()
    assert _resolve_step_index(args.until_step, steps) < _model_phase_index(steps)


def test_a_calibration_case_is_prepared_as_a_simulation(tmp_path: Path) -> None:
    root, plan = _project(tmp_path)

    flags = task_flags(root, plan / f"{CALIBRATION}.toml", phase="prepare")

    assert flags == ["--until", "load_data", "--set", "workflow.mode=simulation"]
    args = _parsed(plan / f"{CALIBRATION}.toml", flags)
    assert args.set_overrides == ["workflow.mode=simulation"]


def test_a_first_solve_resumes_nothing_and_freezes_only_with_a_lock(tmp_path: Path) -> None:
    root, plan = _project(tmp_path)
    case = plan / "J001-base.toml"

    assert task_flags(root, case, phase="solve") == []
    (root / "hydromodpy.lock").write_text("pinned\n")
    assert task_flags(root, case, phase="solve") == ["--frozen"]


def test_a_simulation_left_failed_resumes_in_place(tmp_path: Path) -> None:
    root, plan = _project(tmp_path)
    (root / "hydromodpy.lock").write_text("pinned\n")
    claim = claim_run_directory(root, "J001-base", case_id="J001-base", project="p")
    finish_attempt(claim.run_dir, status="failed", exit_code=1, error=RuntimeError("x"))

    flags = task_flags(root, plan / "J001-base.toml", phase="solve")

    assert flags == ["--frozen", "--resume", "J001-base"]
    assert _parsed(plan / "J001-base.toml", flags).resume == "J001-base"


def test_a_calibration_never_takes_resume(tmp_path: Path) -> None:
    root, plan = _project(tmp_path)
    (root / "hydromodpy.lock").write_text("pinned\n")
    claim = claim_run_directory(root, CALIBRATION, case_id=CALIBRATION, project="p")
    finish_attempt(claim.run_dir, status="failed", exit_code=1, error=RuntimeError("x"))

    assert task_flags(root, plan / f"{CALIBRATION}.toml", phase="solve") == ["--frozen"]


def test_a_case_outside_the_plan_or_a_bad_phase_is_refused(tmp_path: Path) -> None:
    root, plan = _project(tmp_path)
    stray = plan / "J999-base.toml"
    stray.write_text('[site]\nname = "J999"\n')

    with pytest.raises(JobUsageError, match="not a case of plan"):
        task_flags(root, stray, phase="solve")
    with pytest.raises(JobUsageError, match="phase"):
        task_flags(root, plan / "J001-base.toml", phase="data")


def test_the_lock_is_written_from_the_workspace_of_the_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, plan = _project(tmp_path)
    seen: dict[str, Path] = {}

    def data_dir(case_path: Path) -> Path:
        seen["case"] = case_path
        return tmp_path / "workspace" / "data"

    def write(project_root: Path, data: Path) -> Path:
        seen["root"], seen["data"] = project_root, data
        return project_root / "hydromodpy.lock"

    monkeypatch.setattr(slurm, "workspace_data_dir", data_dir)
    monkeypatch.setattr("hydromodpy.project.lockfile.write_project_lockfile", write)

    path = write_lock(root, Path("plan") / plan.name / "J001-base.toml")

    assert path == root.resolve() / "hydromodpy.lock"
    assert seen["case"] == root.resolve() / "plan" / plan.name / "J001-base.toml"
    assert seen["data"] == tmp_path / "workspace" / "data"
