"""The runtime objects of the solver port: ``RunSlot``, ``SolverRun`` and ``RunContext``."""

from __future__ import annotations

import dataclasses
import pickle
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.core.state.run_state import RunState, WorkflowContext
from hydromodpy.solver.base.plan import (
    ProcessRun,
    RunContext,
    RunSlot,
    SimulationPlan,
    SolverRun,
)

RUN = ProcessRun(
    id="flow_main::modflow6", process_id="flow_main", process_type="flow", solver="modflow6"
)
PLAN = SimulationPlan(name="demo", description="demo", runs=(RUN,))


def test_a_slot_names_the_folder_its_run_writes_into() -> None:
    slot = RunSlot(Path("scratch"), "island")

    assert slot.directory == Path("scratch") / "island"
    assert (slot.stop_before_solve, slot.bin_dir, slot.shared_forcing_dir) == (False, None, None)
    assert slot.hand_off == frozenset()


def test_a_slot_holds_paths_whatever_it_was_given() -> None:
    slot = RunSlot("scratch", "island", bin_dir="bin", shared_forcing_dir="shared")

    assert slot.folder == Path("scratch")
    assert slot.bin_dir == Path("bin")
    assert slot.shared_forcing_dir == Path("shared")


def test_a_slot_holds_the_names_a_later_run_reads_of_it() -> None:
    """hand_off lists the products a run after this one reads, held as a frozenset of names."""
    slot = RunSlot(Path("scratch"), "island", hand_off=("face_flow", "particles/x", "face_flow"))

    assert slot.hand_off == frozenset({"face_flow", "particles/x"})
    assert isinstance(slot.hand_off, frozenset)


@pytest.mark.parametrize("name", ["", "   "])
def test_a_slot_refuses_a_blank_name(name: str) -> None:
    with pytest.raises(SolverInputError, match="cannot be blank"):
        RunSlot(Path("scratch"), name)


@pytest.mark.parametrize(
    ("value", "member"),
    [
        (RunSlot(Path("scratch"), "island"), "name"),
        (SolverRun(slot=RunSlot(Path("scratch"), "island")), "solved"),
    ],
    ids=["slot", "solver run"],
)
def test_the_slot_and_the_solver_run_are_frozen(value: object, member: str) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, member, "changed")


def test_a_built_run_is_neither_written_nor_solved() -> None:
    slot = RunSlot(Path("scratch"), "island")
    built = SolverRun(slot=slot, solver_model=object())

    assert (built.written, built.solved, built.output_dir, built.input_files) == (
        False,
        False,
        None,
        (),
    )
    assert built.model is None and built.options is None
    assert built.metrics == {} and built.initial_state_converged is None


def test_a_solver_run_holds_its_output_folder_and_files_as_given_types() -> None:
    solved = SolverRun(
        slot=RunSlot(Path("scratch"), "island"),
        output_dir="scratch/island",
        input_files=["island.npf", Path("island.sto")],
    )

    assert solved.output_dir == Path("scratch/island")
    assert solved.input_files == ("island.npf", "island.sto")


def test_a_solver_run_needs_a_slot() -> None:
    with pytest.raises(TypeError, match="RunSlot"):
        SolverRun(slot=SimpleNamespace(folder=Path("scratch"), name="island"))


def test_a_solver_run_without_a_solver_model_crosses_a_process_boundary() -> None:
    """A worker of a parallel calibration sends the runs it keeps over a pipe."""
    solved = SolverRun(
        slot=RunSlot(Path("scratch"), "island", bin_dir=Path("bin")),
        output_dir=Path("scratch/island"),
        input_files=("island.npf",),
        written=True,
        solved=True,
        metrics={"flow_solve_time_seconds": 1.5},
        initial_state_converged=True,
    )

    assert pickle.loads(pickle.dumps(solved)) == solved


def _workflow(**solver_runs: SolverRun) -> WorkflowContext:
    ctx = WorkflowContext(cfg=None, config_path=Path("project.toml"), raw_toml={})
    ctx.execution.solver_runs.update(solver_runs)
    return ctx


def test_run_context_of_hands_over_what_the_run_produced() -> None:
    produced = SolverRun(slot=RunSlot(Path("scratch"), "island"), solved=True)
    ctx = _workflow(**{RUN.id: produced})

    run_ctx = RunContext.of(ctx, plan=PLAN, run=RUN, store="store")

    assert run_ctx.solver_run is produced
    assert run_ctx.store == "store"
    assert run_ctx.upstream == ()
    assert isinstance(run_ctx.state, RunState)


def test_run_context_of_a_run_that_has_not_run_carries_nothing() -> None:
    assert RunContext.of(_workflow(), plan=PLAN, run=RUN).solver_run is None


def test_a_run_context_keeps_its_upstream_runs_as_a_tuple() -> None:
    upstream = [SolverRun(slot=RunSlot(Path("scratch"), "island"), solver_model=object())]

    run_ctx = RunContext(plan=PLAN, run=RUN, state=RunState(), upstream=upstream)

    assert run_ctx.upstream == tuple(upstream)


def test_a_run_context_carries_no_model_and_no_folder_of_its_own() -> None:
    """What a run produced travels as one ``SolverRun``, not as loose members."""
    members = {field.name for field in dataclasses.fields(RunContext)}

    assert members == {"plan", "run", "state", "store", "solver_run", "upstream"}
