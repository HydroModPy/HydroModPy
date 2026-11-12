"""Lanes of a trial: the last solved trial of a lane is the parent of the next one.

A lane is taken by one trial at a time, given back with the runs of a completed
trial, which it adopts by copying their input files and pointing their solver
object at the copy, and given back empty after a failure.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.runners.lanes import (
    TrialParents,
    open_trial_lanes,
    release_trial_lanes,
)
from hydromodpy.calibration.runners.sandbox import KEEP_ENV_VAR, lane_dir, lane_dirs
from hydromodpy.solver.base.plan import RunSlot, SolverRun

INPUT_FILES = ("sim.nam", "model.npf", "model.disv")


class _Sim:
    def __init__(self, path: Path) -> None:
        self.sim_path = os.fspath(path)

    def set_sim_path(self, path: str) -> None:
        self.sim_path = path


def _solved_run(folder: Path, *, files: tuple[str, ...] = INPUT_FILES, movable: bool = True):
    folder.mkdir(parents=True, exist_ok=True)
    for name in files:
        (folder / name).write_text(name, encoding="utf-8")
    solver = SimpleNamespace(sim=_Sim(folder)) if movable else SimpleNamespace()
    return SolverRun(
        slot=RunSlot(folder.parent, folder.name),
        solver_model=solver,
        output_dir=folder,
        input_files=files,
        written=True,
        solved=True,
    )


def _parents(tmp_path: Path, **options) -> TrialParents:
    return TrialParents(lambda key: tmp_path / f"base_lane{key}", keep_everything=False, **options)


def test_width_bounds_lanes(tmp_path: Path) -> None:
    parents = _parents(tmp_path, width=1)
    lane = parents.take()
    assert parents.take() is None
    parents.give(lane, None)
    assert parents.take() is lane


GIVEN_UP: tuple[tuple[str, dict], ...] = (
    ("a solver object that cannot move", {"movable": False}),
    ("a run that lists no input file", {"files": ()}),
)


@pytest.mark.parametrize(("case", "options"), GIVEN_UP, ids=[c for c, _ in GIVEN_UP])
def test_unadoptable_run_empties_lane(tmp_path: Path, case: str, options: dict) -> None:
    del case
    parents = _parents(tmp_path)
    lane = parents.take()
    parents.give(lane, {"flow": _solved_run(tmp_path / "t1", **options)})
    assert parents.take().runs == {}


def test_no_scratch_no_lane(tmp_path: Path) -> None:
    assert TrialParents(lambda key: None).take() is None


def test_release_deletes_lane_folders(tmp_path: Path) -> None:
    parents = _parents(tmp_path)
    lane = parents.take()
    parents.give(lane, {"flow": _solved_run(tmp_path / "t1")})
    parents.release()
    assert not lane.directory.exists()
    assert parents.take() is None


def test_release_keeps_folders_when_asked(tmp_path: Path) -> None:
    parents = TrialParents(lambda key: tmp_path / f"base_lane{key}", keep_everything=True)
    lane = parents.take()
    parents.give(lane, {"flow": _solved_run(tmp_path / "t1")})
    parents.release()
    assert (lane.directory / "flow" / "sim.nam").is_file()


def _context(scratch: Path, *, derives: bool = True) -> SimpleNamespace:
    setup = SimpleNamespace(
        run_id="calage", workspace=SimpleNamespace(solver_scratch_folder=scratch)
    )
    return SimpleNamespace(
        ctx=SimpleNamespace(setup=setup), model_from_profiles=derives, parents=None
    )


def test_derived_model_gets_scratch_lanes(tmp_path: Path) -> None:
    trial_ctx = _context(tmp_path)
    open_trial_lanes(trial_ctx)
    lane = trial_ctx.parents.take()
    assert lane.directory == lane_dir(trial_ctx, "1") == tmp_path / "calage_lane1"


def test_release_deletes_every_process_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(KEEP_ENV_VAR, raising=False)
    trial_ctx = _context(tmp_path)
    open_trial_lanes(trial_ctx)
    lane = trial_ctx.parents.take()
    trial_ctx.parents.give(lane, {"flow": _solved_run(tmp_path / "calage_trial000001")})
    worker = lane_dir(trial_ctx, "4242-1")
    worker.mkdir()
    assert lane_dirs(trial_ctx) == [lane.directory, worker]

    release_trial_lanes(trial_ctx)

    assert trial_ctx.parents is None
    assert lane_dirs(trial_ctx) == []
    assert (tmp_path / "calage_trial000001").is_dir()
