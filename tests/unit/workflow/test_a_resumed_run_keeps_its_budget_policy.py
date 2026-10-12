"""A run resumed after its extraction keeps the budget policy it was extracted under.

The policy is decided at planning, with the display flag of the invocation
(``hmp run --no-display`` drops the figures from the consumers). A resume is
another invocation: deciding again could keep a term the store never wrote,
or forget one it did. When the store already says what it kept, the resume
reads it there; otherwise it decides as a fresh run would.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import hydromodpy.workflow.steps.prepare_solver as prepare_solver_module
from hydromodpy.core.budget_terms import BudgetKeep
from hydromodpy.core.state.execution import ExecutionRegistry
from hydromodpy.display.config import DisplayConfig
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.simulation.planning.plan import ProcessRun, SimulationPlan
from hydromodpy.simulation.planning.results_config import ResultsConfig
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.steps.prepare_solver import PrepareSolverStep


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
        setup=SimpleNamespace(workspace=SimpleNamespace(project_root=Path("."))),
        execution=ExecutionRegistry(simulation_plan=_plan(), lightweight=False),
        budget_terms=None,
    )


def _extracted_store(tmp_path: Path, keep: BudgetKeep | None, written=()) -> _Store:
    fields = tmp_path / "fields.zarr"
    sz = SimulationZarr.create(fields, n_cells=2, n_layers=1)
    try:
        if keep is not None:
            sz.write_budget_policy(keep, written)
    finally:
        sz.close()
    return _Store(fields)


def _resume(monkeypatch, ctx, store: _Store, *, skip_display: bool) -> None:
    @contextmanager
    def _scope(_ctx):
        yield store

    monkeypatch.setattr(prepare_solver_module, "run_catalog", _scope)
    prior = PipelineState(
        run_id="run", step_index=5, data={"ctx": ctx, "skip_display": skip_display}
    )
    PrepareSolverStep().rebuild_state(prior_state=prior, workspace=Path("."), run_id="run")


def test_a_run_extracted_with_the_whole_budget_resumes_with_it(monkeypatch, tmp_path) -> None:
    # The file now says false; the store was extracted under "all".
    ctx = _ctx(keep_per_cell_budget=False)
    store = _extracted_store(tmp_path, BudgetKeep.everything(), written=("drain", "recharge"))

    _resume(monkeypatch, ctx, store, skip_display=True)

    assert ctx.budget_terms == BudgetKeep.everything()


def test_a_consumers_run_resumes_with_the_terms_it_kept(monkeypatch, tmp_path) -> None:
    # Extracted with the figures, resumed with --no-display: the figure terms stay.
    ctx = _ctx(keep_per_cell_budget=False)
    store = _extracted_store(tmp_path, BudgetKeep.of_terms(("recharge",)))

    _resume(monkeypatch, ctx, store, skip_display=True)

    assert ctx.budget_terms == BudgetKeep.of_terms(("recharge",))


def test_a_run_resumed_before_its_extraction_decides_its_policy(monkeypatch, tmp_path) -> None:
    ctx = _ctx(keep_per_cell_budget=False)
    store = _extracted_store(tmp_path, None)

    _resume(monkeypatch, ctx, store, skip_display=True)

    assert ctx.budget_terms == BudgetKeep.of_terms(())


def test_a_resume_without_a_field_store_creates_none(monkeypatch, tmp_path) -> None:
    ctx = _ctx(keep_per_cell_budget=False)
    store = _Store(tmp_path / "fields.zarr")

    _resume(monkeypatch, ctx, store, skip_display=False)

    assert ctx.budget_terms == BudgetKeep.of_terms(("recharge",))
    assert not store.fields.exists()


def test_a_fresh_run_decides_again_whatever_the_context_carries() -> None:
    # The Project facade reuses one context: the previous run's policy and
    # sim_id are still on it when the next run is planned.
    ctx = _ctx(keep_per_cell_budget=True)
    ctx.budget_terms = BudgetKeep.of_terms(("drain",))

    prepare_solver_module._resolve_plan_and_results(ctx, skip_display=False)

    assert ctx.budget_terms == BudgetKeep.everything()
