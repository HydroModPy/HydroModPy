"""The post-run path hands the extractor the per-cell budget the run keeps.

The plan decides it. A direct call without a plan keeps everything, which is
the default; with ``keep_per_cell_budget = false`` only the plan knows the
consumers, so the call must say what it keeps.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import hydromodpy.simulation.extraction.post_run as post_run_module
from hydromodpy.core.budget_terms import BudgetKeep
from hydromodpy.core.state.run_state import RunState
from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan
from hydromodpy.simulation.planning.results_config import ResultsConfig
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.modflow_nwt.nwt import ModflowConfig


class _Extractor:
    category = "lumped"

    def __init__(self) -> None:
        self.kwargs: list[dict] = []

    def extract(self, sim_id, solver_output_dir, store, *, budget_terms=None, **kwargs) -> None:
        self.kwargs.append({"budget_terms": budget_terms, **kwargs})

    def derive(self, *_args) -> None:
        raise AssertionError("every derived field is rebuilt on read")


class _Zarr:
    drain_band_depth_m = None

    def close(self) -> None:
        pass


class _Store:
    project_path = Path(".")

    def __init__(self) -> None:
        self.zarr = _Zarr()

    def open_zarr(self, _sim_id):
        return self.zarr


@pytest.fixture
def extractor(monkeypatch) -> _Extractor:
    extractor = _Extractor()
    monkeypatch.setattr(
        post_run_module,
        "get_solver_registry_provider",
        lambda: SimpleNamespace(get_extractor_instance=lambda *_: extractor),
    )
    monkeypatch.setattr(post_run_module, "_finalize_run_provenance", lambda **_kwargs: None)
    monkeypatch.setattr(post_run_module, "cleanup_solver_outputs", lambda **_kwargs: None)
    monkeypatch.setattr(
        "hydromodpy.simulation.extraction.derivation.fit_metrics.write_fit_metrics",
        lambda *_args: None,
    )
    return extractor


def _context(tmp_path: Path) -> RunContext:
    run = ProcessRun(
        id="flow_main::fake", process_id="flow_main", process_type="flow", solver="fake"
    )
    plan = SimulationPlan(name="demo", description="demo", runs=(run,))
    state = RunState(
        cfg=SimpleNamespace(modflownwt=ModflowConfig(), solver=SolverConfig(), observation=None),
        setup=SimpleNamespace(time_grid=None),
    )
    return RunContext(plan=plan, run=run, state=state, output_dir=tmp_path)


def test_extraction_passes_the_planned_terms(tmp_path, extractor) -> None:
    planned = BudgetKeep.of_terms(("drain",))

    post_run_module.extract_run_outputs(
        ctx=_context(tmp_path),
        sim_id="sim",
        results_config=ResultsConfig(keep_per_cell_budget=False),
        store=_Store(),
        budget_terms=planned,
    )

    assert extractor.kwargs[0]["budget_terms"] is planned


def test_a_direct_post_run_keeps_everything_by_default(tmp_path, extractor) -> None:
    post_run_module.post_run_results(
        ctx=_context(tmp_path),
        sim_id="sim-12345678",
        results_config=ResultsConfig(),
        store=_Store(),
    )

    assert extractor.kwargs[0]["budget_terms"] == BudgetKeep.everything()


def test_a_direct_post_run_passes_the_plan_terms(tmp_path, extractor) -> None:
    planned = BudgetKeep.of_terms(("recharge",))

    post_run_module.post_run_results(
        ctx=_context(tmp_path),
        sim_id="sim-12345678",
        results_config=ResultsConfig(keep_per_cell_budget=False),
        store=_Store(),
        budget_terms=planned,
    )

    assert extractor.kwargs[0]["budget_terms"] is planned


def test_a_direct_post_run_without_a_plan_refuses_the_consumers_policy(tmp_path, extractor) -> None:
    with pytest.raises(ValueError, match="pass budget_terms"):
        post_run_module.post_run_results(
            ctx=_context(tmp_path),
            sim_id="sim-12345678",
            results_config=ResultsConfig(keep_per_cell_budget=False),
            store=_Store(),
        )
    assert extractor.kwargs == []


def test_derive_writes_the_drain_band_and_calls_no_extractor_derive(tmp_path, extractor) -> None:
    store = _Store()

    post_run_module.derive_run_outputs(
        ctx=_context(tmp_path),
        sim_id="sim",
        results_config=ResultsConfig(),
        store=store,
    )

    assert store.zarr.drain_band_depth_m == float(SolverConfig().drain_band_depth_m)
