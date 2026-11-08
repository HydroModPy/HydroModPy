"""What the workflow does with the solver outputs of a run: extract, derive, cleanup.

Each function reads one ``RunContext`` whose ``solver_run`` the runner recorded.
The extract step hands the adapter of the backend that solver run and the
``Retention`` of the run, and nothing else. The adapter reads its own files.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.exceptions import ConfigError, NothingThereError, SolverInputError
from hydromodpy.core.state.run_state import RunState
from hydromodpy.model.model import ModelOptions
from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.plan import ProcessRun, RunContext, RunSlot, SimulationPlan, SolverRun
from hydromodpy.workflow.steps.run_outputs import (
    cleanup_solver_outputs,
    derive_run_outputs,
    extract_run_outputs,
)
from tests._helpers.fake_solvers import fake_adapter
from tests._helpers.model_factory import make_model
from tests.unit.solver.modflow_common.solver_runs import keep_all, retention, solved_run


class _Zarr:
    drain_band_depth_m = None

    def close(self) -> None:
        pass


class _Store:
    """The open store of a run: it names its run and opens a field store."""

    sim_id = "sim-12345678"
    project_path = Path(".")

    def __init__(self) -> None:
        self.zarr = _Zarr()

    def open_zarr(self, _sim_id: str) -> _Zarr:
        return self.zarr


class _Seen:
    """What the adapter registered by one test received."""

    def __init__(self) -> None:
        self.extracted: list[tuple[SolverRun, Any, Retention]] = []
        self.cleaned: list[SolverRun] = []


def _install(monkeypatch, isolated_solvers, *, category: str = "distributed") -> _Seen:
    """Register ``flow_fake_solver`` with an adapter that records its calls, and stub the rest."""
    seen = _Seen()

    def extract(self, solver_run: SolverRun, store: Any, retention: Retention) -> None:
        seen.extracted.append((solver_run, store, retention))

    def cleanup(self, solver_run: SolverRun) -> None:
        seen.cleaned.append(solver_run)
        shutil.rmtree(solver_run.output_dir)

    isolated_solvers.solvers.register(
        fake_adapter("fake_solver", category=category, extract=extract, cleanup=cleanup)
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.run_outputs._finalize_run_provenance", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.run_outputs._keep_the_criterion_recharge",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "hydromodpy.results.derive.catchment_aggregation.aggregate_catchment_timeseries",
        lambda sim_id, store, **kwargs: None,
    )
    return seen


def _context(
    solver_name: str = "fake_solver",
    *,
    process_type: str = "flow",
    solver_run: SolverRun | None = None,
) -> RunContext:
    run = ProcessRun(
        id=f"{process_type}_main::{solver_name}",
        process_id=f"{process_type}_main",
        process_type=process_type,
        solver=solver_name,
    )
    plan = SimulationPlan(name="test", description="test", runs=(run,))
    return RunContext(
        plan=plan, run=run, state=RunState(cfg=SimpleNamespace()), solver_run=solver_run
    )


def _solved_in(tmp_path: Path, **members: Any) -> SolverRun:
    solver_dir = tmp_path / "solver_out"
    solver_dir.mkdir()
    (solver_dir / "model.hds").write_text("head data")
    return solved_run(solver_dir, **members)


def test_the_adapter_receives_the_solver_run_and_the_retention_untouched(
    tmp_path, monkeypatch, isolated_solvers
) -> None:
    seen = _install(monkeypatch, isolated_solvers)
    solver_run = _solved_in(tmp_path)
    planned = retention(BudgetKeep.of_terms(("drain",)))
    store = _Store()

    extract_run_outputs(ctx=_context(solver_run=solver_run), store=store, retention=planned)

    assert len(seen.extracted) == 1
    got_run, got_store, got_retention = seen.extracted[0]
    assert got_run is solver_run and got_store is store and got_retention is planned


def test_a_run_that_is_not_solver_backed_extracts_nothing(
    tmp_path, monkeypatch, isolated_solvers
) -> None:
    seen = _install(monkeypatch, isolated_solvers)
    ctx = _context("catchment", process_type="mesh", solver_run=_solved_in(tmp_path))

    extract_run_outputs(ctx=ctx, store=_Store(), retention=keep_all)

    assert seen.extracted == []


def test_an_unknown_solver_is_refused_by_its_registry(
    tmp_path, monkeypatch, isolated_solvers
) -> None:
    _install(monkeypatch, isolated_solvers)
    ctx = _context("custom_solver", solver_run=_solved_in(tmp_path))

    with pytest.raises(SolverInputError):
        extract_run_outputs(ctx=ctx, store=_Store(), retention=keep_all)


@pytest.mark.parametrize("case", ["no solver run", "no output folder", "a folder that is gone"])
def test_a_run_without_its_output_folder_is_nothing_there(
    case: str, tmp_path, monkeypatch, isolated_solvers
) -> None:
    seen = _install(monkeypatch, isolated_solvers)
    slot = RunSlot(tmp_path, "island")
    solver_run = {
        "no solver run": None,
        "no output folder": SolverRun(slot=slot),
        "a folder that is gone": solved_run(tmp_path / "gone"),
    }[case]

    with pytest.raises(NothingThereError, match="Solver output directory is missing"):
        extract_run_outputs(ctx=_context(solver_run=solver_run), store=_Store(), retention=keep_all)
    assert seen.extracted == []


def test_the_solver_files_go_when_the_run_does_not_keep_them(
    tmp_path, monkeypatch, isolated_solvers
) -> None:
    seen = _install(monkeypatch, isolated_solvers)
    solver_run = _solved_in(tmp_path)

    cleanup_solver_outputs(
        ctx=_context(solver_run=solver_run), retention=retention(solver_files=False)
    )

    assert not solver_run.output_dir.exists()
    assert seen.cleaned == [solver_run]


def test_the_solver_files_stay_when_the_run_keeps_them(
    tmp_path, monkeypatch, isolated_solvers
) -> None:
    seen = _install(monkeypatch, isolated_solvers)
    solver_run = _solved_in(tmp_path)

    cleanup_solver_outputs(
        ctx=_context(solver_run=solver_run), retention=retention(solver_files=True)
    )

    assert (solver_run.output_dir / "model.hds").exists()
    assert seen.cleaned == []


def test_a_run_with_no_solver_run_has_nothing_to_clean(monkeypatch, isolated_solvers) -> None:
    seen = _install(monkeypatch, isolated_solvers)

    cleanup_solver_outputs(ctx=_context(), retention=keep_all)

    assert seen.cleaned == []


def test_a_failing_cleanup_is_logged_and_does_not_stop_the_run(
    tmp_path, monkeypatch, isolated_solvers
) -> None:
    def cleanup(self, solver_run: SolverRun) -> None:
        raise OSError("locked")

    isolated_solvers.solvers.register(fake_adapter("fake_solver", cleanup=cleanup))

    cleanup_solver_outputs(ctx=_context(solver_run=_solved_in(tmp_path)), retention=keep_all)


def _derived(*, model: Any) -> RunContext:
    return _context(solver_run=SolverRun(slot=RunSlot(Path("scratch"), "island"), model=model))


def test_derive_writes_the_drain_band_of_the_model(monkeypatch, isolated_solvers) -> None:
    _install(monkeypatch, isolated_solvers)
    store = _Store()
    model = make_model(
        options=ModelOptions(
            sink_fill=False,
            drain_band_depth_m=2.5,
            drain_bed_thickness_m=1.0,
            drain_conductance_floor_m2_s=1e-12,
        )
    )

    derive_run_outputs(ctx=_derived(model=model), store=store)

    assert store.zarr.drain_band_depth_m == 2.5


def test_a_distributed_backend_aggregates_the_catchment(monkeypatch, isolated_solvers) -> None:
    _install(monkeypatch, isolated_solvers)
    calls: list[dict] = []
    monkeypatch.setattr(
        "hydromodpy.results.derive.catchment_aggregation.aggregate_catchment_timeseries",
        lambda sim_id, store, **kwargs: calls.append({"sim_id": sim_id, **kwargs}),
    )

    derive_run_outputs(ctx=_derived(model=make_model()), store=_Store())

    assert [call["sim_id"] for call in calls] == ["sim-12345678"]
    assert calls[0]["drainage_outside_routed"] is True, "a model without a network routes nothing"


def test_a_lumped_backend_skips_catchment_aggregation(monkeypatch, isolated_solvers) -> None:
    _install(monkeypatch, isolated_solvers, category="lumped")

    def fail(sim_id, store, **kwargs):
        raise AssertionError("lumped extractors must not aggregate spatial fields")

    monkeypatch.setattr(
        "hydromodpy.results.derive.catchment_aggregation.aggregate_catchment_timeseries", fail
    )

    derive_run_outputs(ctx=_derived(model=make_model()), store=_Store())


@pytest.mark.parametrize("case", ["no solver run", "a solver run without a Model"])
def test_a_run_without_a_model_cannot_be_derived(case: str, monkeypatch, isolated_solvers) -> None:
    _install(monkeypatch, isolated_solvers)
    ctx = _context() if case == "no solver run" else _derived(model=None)

    with pytest.raises(ConfigError, match="no Model to derive from"):
        derive_run_outputs(ctx=ctx, store=_Store())
