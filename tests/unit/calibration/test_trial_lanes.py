"""Tests of `lanes`: the last solved trial of a lane is the parent of the next one.

A lane is taken by one trial at a time, given back with the runs of a completed
trial, which it adopts by copying their input files and pointing their solver
object at the copy, and given back empty after a failure.
"""

from __future__ import annotations

import os
import threading
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


def test_a_new_lane_has_no_parent(tmp_path: Path) -> None:
    lane = _parents(tmp_path).take()
    assert lane is not None
    assert (lane.key, lane.runs, lane.busy) == ("1", {}, True)


def test_a_completed_trial_given_back_is_the_parent_of_the_next(tmp_path: Path) -> None:
    parents = _parents(tmp_path)
    lane = parents.take()
    run = _solved_run(tmp_path / "base_trial000001")
    parents.give(lane, {"flow": run})

    again = parents.take()
    assert again is lane
    adopted = again.runs["flow"]
    assert adopted.output_dir == lane.directory / "flow"
    assert sorted(path.name for path in adopted.output_dir.iterdir()) == sorted(INPUT_FILES)
    assert run.solver_model.sim.sim_path == os.fspath(adopted.output_dir)
    assert adopted.solver_model is run.solver_model


def test_only_the_input_files_are_copied(tmp_path: Path) -> None:
    parents = _parents(tmp_path)
    lane = parents.take()
    trial = tmp_path / "base_trial000001"
    run = _solved_run(trial)
    (trial / "model.hds").write_text("heads", encoding="utf-8")
    parents.give(lane, {"flow": run})
    assert not (lane.directory / "flow" / "model.hds").exists()
    assert (trial / "model.hds").is_file()


def test_two_takes_never_hand_out_the_same_lane(tmp_path: Path) -> None:
    parents = _parents(tmp_path)
    first = parents.take()
    parents.give(first, {"flow": _solved_run(tmp_path / "t1")})
    taken = [parents.take(), parents.take()]
    assert taken[0] is first
    assert taken[1] is not first
    assert taken[1].runs == {}


def test_two_threads_never_take_the_same_lane(tmp_path: Path) -> None:
    parents = _parents(tmp_path)
    taken: list = []
    guard = threading.Lock()

    def take() -> None:
        lane = parents.take()
        with guard:
            taken.append(lane)

    threads = [threading.Thread(target=take) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len({id(lane) for lane in taken}) == 8


def test_the_width_bounds_the_lanes(tmp_path: Path) -> None:
    parents = _parents(tmp_path, width=1)
    lane = parents.take()
    assert parents.take() is None
    parents.give(lane, None)
    assert parents.take() is lane


def test_a_failed_trial_gives_nothing_back(tmp_path: Path) -> None:
    parents = _parents(tmp_path)
    lane = parents.take()
    parents.give(lane, {"flow": _solved_run(tmp_path / "t1")})
    lane = parents.take()
    parents.give(lane, None)
    assert parents.take().runs == {}


GIVEN_UP: tuple[tuple[str, dict], ...] = (
    ("a solver object that cannot move", {"movable": False}),
    ("a run that lists no input file", {"files": ()}),
)


@pytest.mark.parametrize(("case", "options"), GIVEN_UP, ids=[c for c, _ in GIVEN_UP])
def test_a_run_that_cannot_be_adopted_leaves_its_lane_empty(
    tmp_path: Path, case: str, options: dict
) -> None:
    del case
    parents = _parents(tmp_path)
    lane = parents.take()
    parents.give(lane, {"flow": _solved_run(tmp_path / "t1", **options)})
    assert parents.take().runs == {}


def test_a_lane_without_a_scratch_is_never_opened(tmp_path: Path) -> None:
    assert TrialParents(lambda key: None).take() is None


def test_release_deletes_the_lane_folders_and_hands_out_nothing(tmp_path: Path) -> None:
    parents = _parents(tmp_path)
    lane = parents.take()
    parents.give(lane, {"flow": _solved_run(tmp_path / "t1")})
    parents.release()
    assert not lane.directory.exists()
    assert parents.take() is None


def test_release_keeps_the_folders_under_the_keep_variable(tmp_path: Path) -> None:
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


def test_a_context_that_derives_its_model_gets_lanes_in_its_scratch(tmp_path: Path) -> None:
    trial_ctx = _context(tmp_path)
    open_trial_lanes(trial_ctx)
    lane = trial_ctx.parents.take()
    assert lane.directory == lane_dir(trial_ctx, "1") == tmp_path / "calage_lane1"


def test_a_context_that_builds_each_trial_gets_no_lane(tmp_path: Path) -> None:
    trial_ctx = _context(tmp_path, derives=False)
    open_trial_lanes(trial_ctx)
    assert trial_ctx.parents is None


def test_release_trial_lanes_deletes_the_lanes_of_every_process(
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
