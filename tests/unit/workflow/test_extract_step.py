from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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
    results = ResultsConfig(export={"csv_timeseries": False})
    output_dir = tmp_path / "solver"
    output_dir.mkdir()
    calls: list[tuple[str, str, Path]] = []

    def _extract_run_outputs(*, ctx, sim_id, results_config, store) -> None:
        calls.append((ctx.run.id, sim_id, ctx.state.execution.output_dirs_by_run_id[ctx.run.id]))
        assert results_config is results
        assert store == "store"

    monkeypatch.setattr(
        "hydromodpy.simulation.extraction.post_run.extract_run_outputs",
        _extract_run_outputs,
    )

    ctx = SimpleNamespace(
        execution=SimpleNamespace(
            lightweight=False,
            simulation_plan=plan,
            output_dirs_by_run_id={run.id: output_dir},
        ),
        store="store",
        sim_id="sim-1",
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results)),
        effective_results_config=results,
    )
    state = PipelineState(run_id="rid", data={"ctx": ctx})

    out = ExtractStep().run(state)

    assert calls == [(run.id, "sim-1", output_dir)]
    assert out.data["extraction_summary"] == {"runs": 1}
