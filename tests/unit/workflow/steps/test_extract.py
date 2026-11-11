"""The extract step."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.state.run_state import ExecutionRegistry
from hydromodpy.solver.base.plan import ProcessRun, RunSlot, SimulationPlan, SolverRun
from hydromodpy.solver.base.results_config import ResultsConfig
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.extract import ExtractStep, retention_of


def _solved(output_dir: Path) -> SolverRun:
    """The solver run a finished solve recorded for its folder."""
    return SolverRun(
        slot=RunSlot(output_dir.parent, output_dir.name),
        output_dir=output_dir,
        written=True,
        solved=True,
    )


def test_extract_step_extracts_solver_outputs(monkeypatch, tmp_path: Path) -> None:
    run = ProcessRun(
        id="flow_main::fake",
        process_id="flow_main",
        process_type="flow",
        solver="fake",
    )
    plan = SimulationPlan(name="run", description="run", runs=(run,))
    results = ResultsConfig()
    output_dir = tmp_path / "solver"
    output_dir.mkdir()
    calls: list[tuple[str, Path]] = []

    planned = BudgetKeep.of_terms(("drain",))

    def _extract_run_outputs(*, ctx, store, retention) -> None:
        calls.append((ctx.run.id, ctx.solver_run.output_dir))
        assert store == "store"
        assert retention.budget is planned
        assert retention.solver_files is False

    monkeypatch.setattr(
        "hydromodpy.workflow.steps.run_outputs.extract_run_outputs",
        _extract_run_outputs,
    )

    ingested: list[tuple[object, str]] = []
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.extract.step_ingest_observations",
        lambda ctx, sim_id, *, store: ingested.append((ctx, sim_id)),
    )

    @contextmanager
    def _fake_scope(_ctx):
        yield "store"

    monkeypatch.setattr("hydromodpy.workflow.steps.extract.run_store", _fake_scope)

    ctx = SimpleNamespace(
        # A real registry, not a namespace: the step builds its run contexts
        # through ``RunContext.of``, so a double has to carry every scope that
        # path reads rather than the ones this test happens to assert on.
        execution=ExecutionRegistry(
            lightweight=False,
            simulation_plan=plan,
            solver_runs={run.id: _solved(output_dir)},
        ),
        setup=SimpleNamespace(workspace=object()),
        sim_id="sim-1",
        loaded_data=None,
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results)),
        budget_terms=planned,
    )
    state = PipelineState(run_id="rid", data={"ctx": ctx})

    out = ExtractStep().run(state)

    assert calls == [(run.id, output_dir)]
    # Observations are ingested in the same step, after solver extraction.
    assert ingested == [(ctx, "sim-1")]
    assert out.data["extraction_summary"] == {"runs": 1}


def _uncomputed_context(tmp_path: Path, results: ResultsConfig, display) -> SimpleNamespace:
    run = ProcessRun(
        id="flow_main::modflow6",
        process_id="flow_main",
        process_type="flow",
        solver="modflow6",
    )
    plan = SimulationPlan(name="run", description="run", runs=(run,))
    output_dir = tmp_path / "solver"
    output_dir.mkdir()
    ctx = SimpleNamespace(
        execution=ExecutionRegistry(
            lightweight=False,
            simulation_plan=plan,
            solver_runs={run.id: _solved(output_dir)},
        ),
        setup=SimpleNamespace(workspace=object()),
        sim_id="sim-1",
        loaded_data=None,
        cfg=SimpleNamespace(
            simulation=SimpleNamespace(results=results),
            display=display,
            export=[],
            calibration=None,
            observation=None,
        ),
        level=None,
        budget_terms=None,
    )
    return ctx


def _stub_extraction(monkeypatch) -> list[BudgetKeep]:
    seen: list[BudgetKeep] = []
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.run_outputs.extract_run_outputs",
        lambda *, retention, **_kwargs: seen.append(retention.budget),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.extract.step_ingest_observations",
        lambda ctx, sim_id, *, store: None,
    )

    @contextmanager
    def _fake_scope(_ctx):
        yield "store"

    monkeypatch.setattr("hydromodpy.workflow.steps.extract.run_store", _fake_scope)
    return seen


def test_extract_step_decides_the_budget_when_planning_did_not(monkeypatch, tmp_path) -> None:
    """A pipeline entered at extraction still extracts under the run's policy."""
    from hydromodpy.display.config import DisplayConfig

    seen = _stub_extraction(monkeypatch)
    ctx = _uncomputed_context(
        tmp_path,
        ResultsConfig(keep_per_cell_budget=False),
        DisplayConfig(figures=["recharge_map"]),
    )

    ExtractStep().run(PipelineState(run_id="rid", data={"ctx": ctx}))

    assert seen == [BudgetKeep.of_terms(("recharge",))]
    assert ctx.budget_terms == BudgetKeep.of_terms(("recharge",))


def test_no_display_keeps_what_the_figures_read(monkeypatch, tmp_path) -> None:
    """A display choice of the launch changes no data."""
    import hydromodpy.display.figure_registry as figure_registry
    from hydromodpy.core.budget.terms import budget_terms_for_fields
    from hydromodpy.display.config import DisplayConfig

    seen = _stub_extraction(monkeypatch)
    results = ResultsConfig(keep_per_cell_budget=False)
    ctx = _uncomputed_context(tmp_path, results, DisplayConfig(figures=["recharge_map"]))
    ExtractStep().run(PipelineState(run_id="rid", data={"ctx": ctx, "skip_display": True}))
    spec = figure_registry.get("recharge_map").spec
    assert seen[-1] == BudgetKeep.of_terms(
        budget_terms_for_fields((*spec.required_fields, *spec.optional_fields))
    )


@pytest.mark.parametrize("keep", [False, True])
def test_the_retention_of_a_run_keeps_the_solver_files_its_results_table_asks(
    tmp_path, keep: bool
) -> None:
    ctx = _uncomputed_context(tmp_path, ResultsConfig(keep_solver_files=keep), display=None)
    ctx.budget_terms = BudgetKeep.of_terms(("drain",))

    retention = retention_of(ctx, ctx.execution.simulation_plan)

    assert retention.solver_files is keep
    assert retention.budget == BudgetKeep.of_terms(("drain",)), "the planned terms are kept as is"


def test_a_run_that_keeps_every_per_cell_budget_term_says_so(tmp_path) -> None:
    ctx = _uncomputed_context(tmp_path, ResultsConfig(), display=None)

    retention = retention_of(ctx, ctx.execution.simulation_plan)

    assert retention.budget == BudgetKeep.everything()
    assert ctx.budget_terms == BudgetKeep.everything(), "the decision is kept on the context"


def test_the_retention_of_a_run_reads_the_level_of_the_context(tmp_path) -> None:
    """A kept trial keeps neither the solver files nor the face flows, whatever it asks."""
    ctx = _uncomputed_context(
        tmp_path,
        ResultsConfig(keep_solver_files=True, keep_face_flows=True),
        display=None,
    )
    ctx.level = "research"
    ctx.budget_terms = BudgetKeep.of_terms(("drain",))

    retention = retention_of(ctx, ctx.execution.simulation_plan)

    assert retention.level == "research"
    assert retention.solver_files is False
    assert retention.face_flows is False
    assert retention.budget == BudgetKeep.of_terms(("drain",))


def test_the_retention_of_a_run_defaults_to_the_result_level(tmp_path) -> None:
    ctx = _uncomputed_context(tmp_path, ResultsConfig(), display=None)

    retention = retention_of(ctx, ctx.execution.simulation_plan)

    assert retention.level == "result"


def test_a_run_that_keeps_no_catalog_extracts_nothing(monkeypatch, tmp_path) -> None:
    ctx = _uncomputed_context(tmp_path, ResultsConfig(), display=None)
    ctx.execution.lightweight = True
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.run_outputs.extract_run_outputs",
        lambda **_kwargs: pytest.fail("a run that keeps no catalog extracts nothing"),
    )

    out = ExtractStep().run(PipelineState(run_id="rid", data={"ctx": ctx}))

    assert out.data["extraction_summary"] == {"runs": 0}


# --- test_modpath_ingestion ---
# Unit tests for ``workflow.steps.extract``: the seepage raster rebuilt from a run store.


class _FakeRasterSrc:
    height = 2
    width = 2

    def __enter__(self) -> _FakeRasterSrc:
        return self

    def __exit__(self, *exc: object) -> None:
        pass
