"""The derive step writes no derived field, every one is rebuilt on read.

It releases the solver models (the solver runs stay, without their model) and runs
``derive_run_outputs`` once per solver-backed run. Then it scores the run under its
metric rule and puts the rows and the headline NSE in the facts the seal reads.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import hydromodpy.workflow.steps.derive as derive_module
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.run_state import ExecutionRegistry
from hydromodpy.results.score import score_run_under_its_rule
from hydromodpy.solver.base.plan import ProcessRun, RunSlot, SimulationPlan, SolverRun
from hydromodpy.solver.base.results_config import ResultsConfig
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.derive import DeriveStep


def make_ctx(*, catalogued: bool, plan: SimulationPlan | None) -> SimpleNamespace:
    results = ResultsConfig.model_validate({"persistence": {"save_catalog": catalogued}})
    execution = ExecutionRegistry(simulation_plan=plan, lightweight=False)
    execution.solver_runs["flow_main::modflow6"] = SolverRun(
        slot=RunSlot(Path("scratch"), "island"),
        solver_model=object(),
        output_dir=Path("scratch/island"),
        solved=True,
    )
    return SimpleNamespace(
        sim_id="sim-1",
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results), calibration=None),
        loaded_data=SimpleNamespace(),
        setup=SimpleNamespace(workspace=object()),
        execution=execution,
    )


def make_plan() -> SimulationPlan:
    runs = (
        ProcessRun(
            id="mesh::catchment", process_id="mesh", process_type="mesh", solver="catchment"
        ),
        ProcessRun(
            id="flow_main::modflow6", process_id="flow_main", process_type="flow", solver="modflow6"
        ),
    )
    return SimulationPlan(name="run", description="run", runs=runs)


def test_derivation_runs_once_per_solver_run(monkeypatch) -> None:
    calls: list[dict] = []

    @contextmanager
    def _scope(_ctx):
        yield "store"

    scored: list[tuple] = []
    monkeypatch.setattr(derive_module, "run_store", _scope)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.run_outputs.derive_run_outputs",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(
        derive_module,
        "score_run_under_its_rule",
        lambda cfg, *, store: scored.append((cfg, store)),
    )
    ctx = make_ctx(catalogued=True, plan=make_plan())
    series: list[tuple] = []
    monkeypatch.setattr(
        "hydromodpy.calibration.runners.promotion.write_station_series",
        lambda ctx, *, store, outputs: series.append(
            (
                store,
                outputs,
                [
                    run_id
                    for run_id, run in ctx.execution.solver_runs.items()
                    if run.solver_model is not None
                ],
            )
        ),
    )

    out = DeriveStep().run(
        PipelineState(run_id="r", data={"ctx": ctx, "station_outputs": {"up": "decl"}})
    )

    # The solver models are still there when the series is written, and gone after.
    assert series == [("store", {"up": "decl"}, ["flow_main::modflow6"])]

    assert [call["ctx"].run.id for call in calls] == ["flow_main::modflow6"]
    assert set(calls[0]) == {"ctx", "store"}
    assert scored == [(ctx.cfg, "store")], "the run is scored once the aggregates are written"
    released = ctx.execution.solver_runs["flow_main::modflow6"]
    assert released.solver_model is None
    assert released.output_dir == Path("scratch/island"), "only the solver model is released"
    assert out.step_name == "derive"
    assert "derived_names" not in out.data


def test_no_window_gives_an_empty_headline(tmp_path) -> None:
    from hydromodpy.core.site.config import SiteConfig
    from tests._helpers.run_stores import open_run_store

    cfg = SimpleNamespace(site=SiteConfig(name="nancon", gauge="J0014010"), metrics=None)
    with open_run_store(tmp_path / "demo", "unscored", n_cells=4) as store:
        score_run_under_its_rule(cfg, store=store)

        assert store.facts.score is not None
        assert store.facts.score.value is None and store.facts.score.n_samples == 0
        assert store.facts.metrics == []


def test_step_needs_a_context() -> None:
    with pytest.raises(ConfigError, match="'ctx'"):
        DeriveStep().run(PipelineState(run_id="r", data={}))


def test_run_without_a_store_is_a_noop(monkeypatch) -> None:
    def _fail(_ctx):
        raise AssertionError("a run that keeps no store opens none")

    monkeypatch.setattr(derive_module, "run_store", _fail)
    ctx = make_ctx(catalogued=False, plan=make_plan())

    out = DeriveStep().run(PipelineState(run_id="r", data={"ctx": ctx}))

    assert out.step_name == "derive"


def test_rebuild_lists_nothing() -> None:
    ctx = make_ctx(catalogued=True, plan=make_plan())
    prior = PipelineState(run_id="r", step_index=3, data={"ctx": ctx})

    out = DeriveStep().rebuild_state(prior_state=prior, workspace=None, run_id="r")

    assert out.step_index == 4
    assert out.get("ctx") is ctx
    assert "derived_names" not in out.data
