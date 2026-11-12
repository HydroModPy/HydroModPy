"""``PrepareSolverStep.rebuild_state``: a resumed run keeps the budget policy its store records."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import hydromodpy.workflow.steps.prepare_solver.step as prepare_solver_module
from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.state.run_state import ExecutionRegistry
from hydromodpy.display.config import DisplayConfig
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.solver.base.plan import ProcessRun, SimulationPlan
from hydromodpy.solver.base.results_config import ResultsConfig
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.prepare_solver.step import PrepareSolverStep
from tests._helpers.sealed_runs import write_attempt

# A run resumed after its extraction keeps the budget policy it was extracted under. A resume is
# another invocation (``hmp run --no-display`` changes the figures), so deciding again could keep
# a term the store never wrote. When the store says what it kept, the resume reads it there.


class _Store:
    def __init__(self, fields: Path) -> None:
        self.fields = fields

    def fields_path_for(self, _sim_id: str) -> Path:
        return self.fields

    def open_zarr(self, _sim_id: str) -> SimulationZarr:
        return SimulationZarr(self.fields)


def _plan() -> SimulationPlan:
    run = ProcessRun(
        id="flow_main::modflow6", process_id="flow_main", process_type="flow", solver="modflow6"
    )
    return SimulationPlan(name="run", description="run", runs=(run,))


def _ctx(*, keep_per_cell_budget: bool) -> SimpleNamespace:
    results = ResultsConfig(keep_per_cell_budget=keep_per_cell_budget)
    return SimpleNamespace(
        sim_id="sim-1",
        cfg=SimpleNamespace(
            simulation=SimpleNamespace(results=results),
            display=DisplayConfig(figures=["recharge_map"]),
            export=[],
            calibration=None,
            observation=None,
        ),
        setup=SimpleNamespace(workspace=SimpleNamespace(project_root=Path(".")), products={}),
        execution=ExecutionRegistry(simulation_plan=_plan(), lightweight=False),
        budget_terms=None,
    )


def _extracted_store(tmp_path: Path, keep: BudgetKeep | None, written=()) -> _Store:
    fields = tmp_path / "runs" / "run" / "fields.zarr"
    fields.parent.mkdir(parents=True)
    sz = SimulationZarr.create(fields, n_cells=2, n_layers=1)
    try:
        if keep is not None:
            sz.write_budget_policy(keep, written)
    finally:
        sz.close()
    return _Store(fields)


def _resume(monkeypatch, ctx, store: _Store) -> None:
    @contextmanager
    def _scope(_ctx):
        yield store

    monkeypatch.setattr(prepare_solver_module, "run_store", _scope)
    project = store.fields.parent.parent
    run_dir = write_attempt(project, "runs/run", status="failed", sim_id="sim-1")
    prior = PipelineState(
        run_id="run",
        step_index=5,
        data={"ctx": ctx, "run_dir": run_dir},
    )
    PrepareSolverStep().rebuild_state(prior_state=prior, workspace=project, run_id="run")
    assert ctx.run_dir == run_dir
    assert ctx.sim_id == "sim-1"


def test_whole_budget_resumes_whole(monkeypatch, tmp_path) -> None:
    # The file now says false; the store was extracted under "all".
    ctx = _ctx(keep_per_cell_budget=False)
    store = _extracted_store(tmp_path, BudgetKeep.everything(), written=("drain", "recharge"))

    _resume(monkeypatch, ctx, store)

    assert ctx.budget_terms == BudgetKeep.everything()


def test_consumers_run_keeps_its_terms(monkeypatch, tmp_path) -> None:
    # The store says what the extraction kept, whatever the file says today.
    ctx = _ctx(keep_per_cell_budget=False)
    store = _extracted_store(tmp_path, BudgetKeep.of_terms(("recharge",)))

    _resume(monkeypatch, ctx, store)

    assert ctx.budget_terms == BudgetKeep.of_terms(("recharge",))


def test_resume_before_extraction_decides(monkeypatch, tmp_path) -> None:
    ctx = _ctx(keep_per_cell_budget=False)
    store = _extracted_store(tmp_path, None)

    _resume(monkeypatch, ctx, store)

    assert ctx.budget_terms == BudgetKeep.of_terms(("recharge",))


def test_resume_creates_no_store(monkeypatch, tmp_path) -> None:
    ctx = _ctx(keep_per_cell_budget=False)
    (tmp_path / "runs" / "run").mkdir(parents=True)
    store = _Store(tmp_path / "runs" / "run" / "fields.zarr")

    _resume(monkeypatch, ctx, store)

    assert ctx.budget_terms == BudgetKeep.of_terms(("recharge",))
    assert not store.fields.exists()
