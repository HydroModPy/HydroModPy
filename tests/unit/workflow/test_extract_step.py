from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from hydromodpy.core.state.execution import ExecutionRegistry
from hydromodpy.simulation.planning.plan import ProcessRun, SimulationPlan
from hydromodpy.simulation.planning.results_config import ResultsConfig
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.steps.extract import ExtractStep


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
    calls: list[tuple[str, str, Path]] = []

    def _extract_run_outputs(*, ctx, sim_id, results_config, store) -> None:
        calls.append((ctx.run.id, sim_id, ctx.output_dir))
        assert results_config is results
        assert store == "store"

    monkeypatch.setattr(
        "hydromodpy.simulation.extraction.post_run.extract_run_outputs",
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

    monkeypatch.setattr("hydromodpy.workflow.steps.extract.run_catalog", _fake_scope)

    ctx = SimpleNamespace(
        # A real registry, not a namespace: the step builds its run contexts
        # through ``RunContext.of``, so a double has to carry every scope that
        # path reads rather than the ones this test happens to assert on.
        execution=ExecutionRegistry(
            lightweight=False,
            simulation_plan=plan,
            output_dirs_by_run_id={run.id: output_dir},
        ),
        setup=SimpleNamespace(workspace=object()),
        sim_id="sim-1",
        loaded_data=None,
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results)),
        effective_results_config=results,
    )
    state = PipelineState(run_id="rid", data={"ctx": ctx})

    out = ExtractStep().run(state)

    assert calls == [(run.id, "sim-1", output_dir)]
    # Observations are ingested in the same step, after solver extraction.
    assert ingested == [(ctx, "sim-1")]
    assert out.data["extraction_summary"] == {"runs": 1}
