"""The derive step."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import hydromodpy.workflow.steps.derive as derive_module
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.run_state import ExecutionRegistry
from hydromodpy.results.fit_metrics import score_run_under_its_rule
from hydromodpy.solver.base.plan import ProcessRun, SimulationPlan
from hydromodpy.solver.base.results_config import ResultsConfig
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.derive import DeriveStep

# --- test_derive_step ---
# The derive step writes no derived field: every one is rebuilt on read.
#
# It releases the solver models and runs ``derive_run_outputs`` once per
# solver-backed run, which writes the drain band, the catchment aggregates and
# the observation samples. Then it scores the run under its metric rule and puts
# the rows and the headline NSE in the facts the seal reads.


def _ctx(*, catalogued: bool, plan: SimulationPlan | None) -> SimpleNamespace:
    results = ResultsConfig.model_validate({"persistence": {"save_catalog": catalogued}})
    execution = ExecutionRegistry(simulation_plan=plan, lightweight=False)
    execution.models_by_run_id["flow_main::modflow6"] = object()
    return SimpleNamespace(
        sim_id="sim-1",
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results), calibration=None),
        loaded_data=SimpleNamespace(),
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
    ctx = _ctx(catalogued=True, plan=_plan())
    series: list[tuple] = []
    monkeypatch.setattr(
        "hydromodpy.calibration.runners.promotion.write_station_series",
        lambda ctx, *, store, outputs: series.append(
            (store, outputs, list(ctx.execution.models_by_run_id))
        ),
    )

    out = DeriveStep().run(
        PipelineState(run_id="r", data={"ctx": ctx, "station_outputs": {"up": "decl"}})
    )

    # The models are still there when the series is written, and gone after.
    assert series == [("store", {"up": "decl"}, ["flow_main::modflow6"])]

    assert [call["ctx"].run.id for call in calls] == ["flow_main::modflow6"]
    assert set(calls[0]) == {"ctx", "sim_id", "results_config", "store"}
    assert calls[0]["results_config"] is ctx.cfg.simulation.results
    assert scored == [(ctx.cfg, "store")], "the run is scored once the aggregates are written"
    assert ctx.execution.models_by_run_id == {}
    assert out.step_name == "derive"
    assert "derived_names" not in out.data


def test_the_run_is_scored_under_its_rule_and_the_facts_carry_the_result(tmp_path) -> None:
    """A real store, a simulated series and its observed twin, a window: rows and a headline."""
    import numpy as np
    import pandas as pd

    from hydromodpy.core.site import SiteConfig
    from hydromodpy.results.metric_rule import MetricsConfig, MetricsWindow
    from tests._helpers.run_stores import open_run_store

    index = pd.date_range("2020-01-02", periods=10, freq="D")
    observed = pd.Series(np.linspace(1.0, 2.0, 10), index=index)
    cfg = SimpleNamespace(
        site=SiteConfig(name="nancon", gauge="J0014010"),
        metrics=MetricsConfig(window=MetricsWindow(start="2020-01-01", end="2020-01-31")),
    )
    with open_run_store(tmp_path / "demo", "scored", n_cells=4, n_timesteps=10) as store:
        sid = store.sim_id
        store.facts.period_start = pd.Timestamp("2020-01-01", tz="UTC").to_pydatetime()
        store.write_timeseries(sid, "J0014010", "discharge", observed * 1.0)
        store.write_timeseries(sid, "J0014010", "discharge", observed, source="observed")

        score_run_under_its_rule(cfg, store=store)

        score = store.facts.score
        assert score is not None and score.metric == "nse" and score.station == "J0014010"
        # The observed days are put on the simulated periods before scoring, so
        # a series paired with itself is close to one, not one.
        assert score.value is not None and 0.5 < score.value <= 1.0
        assert score.n_samples > 0 and score.window_end.isoformat() == "2020-01-31"
        metrics = {row.metric for row in store.facts.metrics if row.station == "J0014010"}
        assert {"nse", "kge", "rmse", "nse_log"} <= metrics


def test_without_a_declared_gauge_the_run_is_scored_at_the_gauge_it_deduced(tmp_path) -> None:
    """``[site]`` names no gauge and ``[metrics]`` no station: the gauge of the facts is the one."""
    import numpy as np
    import pandas as pd

    from hydromodpy.core.site import SiteConfig
    from hydromodpy.results.manifest import ManifestSite
    from hydromodpy.results.metric_rule import MetricsConfig, MetricsWindow
    from tests._helpers.run_stores import open_run_store

    index = pd.date_range("2020-01-02", periods=10, freq="D")
    observed = pd.Series(np.linspace(1.0, 2.0, 10), index=index)
    cfg = SimpleNamespace(
        site=SiteConfig(name="nancon"),
        metrics=MetricsConfig(window=MetricsWindow(start="2020-01-01", end="2020-01-31")),
    )
    with open_run_store(tmp_path / "demo", "deduced", n_cells=4, n_timesteps=10) as store:
        sid = store.sim_id
        store.facts.period_start = pd.Timestamp("2020-01-01", tz="UTC").to_pydatetime()
        store.facts.site = ManifestSite(name="nancon", gauge="J0014010", fingerprint="f")
        store.write_timeseries(sid, "J0014010", "discharge", observed * 1.0)
        store.write_timeseries(sid, "J0014010", "discharge", observed, source="observed")

        score_run_under_its_rule(cfg, store=store)

        score = store.facts.score
        assert score is not None and score.station == "J0014010"
        assert score.value is not None and score.n_samples > 0


def test_without_a_window_the_headline_is_empty_and_says_so(tmp_path) -> None:
    from hydromodpy.core.site import SiteConfig
    from tests._helpers.run_stores import open_run_store

    cfg = SimpleNamespace(site=SiteConfig(name="nancon", gauge="J0014010"), metrics=None)
    with open_run_store(tmp_path / "demo", "unscored", n_cells=4) as store:
        score_run_under_its_rule(cfg, store=store)

        assert store.facts.score is not None
        assert store.facts.score.value is None and store.facts.score.n_samples == 0
        assert store.facts.metrics == []


def test_derive_step_without_ctx_raises() -> None:
    with pytest.raises(ConfigError, match="'ctx'"):
        DeriveStep().run(PipelineState(run_id="r", data={}))


def test_derive_step_without_an_index_is_a_noop(monkeypatch) -> None:
    def _fail(_ctx):
        raise AssertionError("a run that keeps no store opens none")

    monkeypatch.setattr(derive_module, "run_store", _fail)
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
