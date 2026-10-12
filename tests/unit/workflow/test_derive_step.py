"""The derive step writes no derived field: every one is rebuilt on read.

It releases the solver models and runs ``derive_run_outputs`` once per
solver-backed run, which writes the drain band, the catchment aggregates, the
observation samples and the fit metrics.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import hydromodpy.workflow.steps.derive as derive_module
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.execution import ExecutionRegistry
from hydromodpy.simulation.planning.plan import ProcessRun, SimulationPlan
from hydromodpy.simulation.planning.results_config import ResultsConfig
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.steps.derive import DeriveStep


def _ctx(*, catalogued: bool, plan: SimulationPlan | None) -> SimpleNamespace:
    results = ResultsConfig.model_validate({"persistence": {"save_catalog": catalogued}})
    execution = ExecutionRegistry(simulation_plan=plan, lightweight=False)
    execution.models_by_run_id["flow_main::modflow6"] = object()
    return SimpleNamespace(
        sim_id="sim-1",
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results)),
        setup=SimpleNamespace(workspace=object()),
        execution=execution,
    )


def _plan() -> SimulationPlan:
    runs = (
        ProcessRun(
            id="mesh::catchment", process_id="mesh", process_type="mesh", solver="catchment"
        ),
        ProcessRun(
            id="flow_main::modflow6", process_id="flow_main", process_type="flow", solver="modflow6"
        ),
    )
    return SimulationPlan(name="run", description="run", runs=runs)


def test_derive_step_runs_the_post_run_derivation_once_per_solver_run(monkeypatch) -> None:
    calls: list[dict] = []

    @contextmanager
    def _scope(_ctx):
        yield "store"

    monkeypatch.setattr(derive_module, "run_catalog", _scope)
    monkeypatch.setattr(
        "hydromodpy.simulation.extraction.post_run.derive_run_outputs",
        lambda **kwargs: calls.append(kwargs),
    )
    ctx = _ctx(catalogued=True, plan=_plan())

    out = DeriveStep().run(PipelineState(run_id="r", data={"ctx": ctx}))

    assert [call["ctx"].run.id for call in calls] == ["flow_main::modflow6"]
    assert set(calls[0]) == {"ctx", "sim_id", "results_config", "store"}
    assert calls[0]["results_config"] is ctx.cfg.simulation.results
    assert ctx.execution.models_by_run_id == {}
    assert out.step_name == "derive"
    assert "derived_names" not in out.data


def test_derive_step_without_ctx_raises() -> None:
    with pytest.raises(ConfigError, match="'ctx'"):
        DeriveStep().run(PipelineState(run_id="r", data={}))


def test_derive_step_without_an_index_is_a_noop(monkeypatch) -> None:
    def _fail(_ctx):
        raise AssertionError("an uncatalogued run opens no index")

    monkeypatch.setattr(derive_module, "run_catalog", _fail)
    ctx = _ctx(catalogued=False, plan=_plan())

    out = DeriveStep().run(PipelineState(run_id="r", data={"ctx": ctx}))

    assert out.step_name == "derive"


def test_derive_step_rebuild_lists_nothing() -> None:
    ctx = _ctx(catalogued=True, plan=_plan())
    prior = PipelineState(run_id="r", step_index=3, data={"ctx": ctx})

    out = DeriveStep().rebuild_state(prior_state=prior, workspace=None, run_id="r")

    assert out.step_index == 4
    assert out.get("ctx") is ctx
    assert "derived_names" not in out.data
