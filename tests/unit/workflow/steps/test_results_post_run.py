"""Tests for workflow/steps/run_outputs.py - post-run hook."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.state.run_state import RunState
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.solver.base.plan import ProcessRun, RunContext, SimulationPlan
from hydromodpy.solver.base.results_config import ResultsConfig
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.workflow.steps.run_outputs import post_run_results
from tests._helpers.fake_solvers import fake_adapter
from tests._helpers.run_stores import open_run_store


@pytest.fixture
def store(tmp_path):
    """The open store of a claimed run, as the pipeline hands it to post-run."""
    run_store = open_run_store(tmp_path / "project", "run", solver="modflow_nwt")
    try:
        yield run_store
    finally:
        run_store.close()


def _build_run_context(
    *,
    solver_name: str,
    process_type: str = "flow",
    solver_output_dir: Path | None = None,
) -> RunContext:
    """Build a minimal RunContext for post_run_results tests.

    The context carries the solver output directory for the
    ``adapter.cleanup(ctx)`` path, plus the ``cfg`` the extraction phase reads
    to hand the configured dry-cell sentinels to the extractor.
    """
    run = ProcessRun(
        id=f"{process_type}_main::{solver_name}",
        process_id=f"{process_type}_main",
        process_type=process_type,
        solver=solver_name,
    )
    plan = SimulationPlan(name="test", description="test", runs=(run,))
    state = RunState(
        cfg=SimpleNamespace(solver=SolverConfig(), domain=DomainConfig()),
    )
    return RunContext(plan=plan, run=run, state=state, output_dir=solver_output_dir)


class _FakeExtractor:
    """The extractor of ``flow_fake_solver``. Built anew per call, so it records on the class."""

    process_type = "flow"
    solver_name = "fake_solver"
    extract_calls: list[dict] = []

    def extract(self, sim_id, solver_output_dir, store, **kwargs) -> None:
        self.extract_calls.append(
            {
                "sim_id": sim_id,
                "solver_output_dir": Path(solver_output_dir),
                "kwargs": dict(kwargs),
            }
        )


class _Registered:
    """What one test registered for ``flow_fake_solver``, and the cleanups its adapter saw."""

    def __init__(self) -> None:
        self.cleanup_calls: list[RunContext] = []


def _install_post_run_stubs(
    monkeypatch, isolated_solvers, *, category: str = "distributed"
) -> _Registered:
    """Register an adapter and an extractor for ``flow_fake_solver``, and stub the aggregation."""
    registered = _Registered()

    def _cleanup(self, ctx: RunContext) -> None:
        registered.cleanup_calls.append(ctx)
        if ctx.output_dir is not None:
            shutil.rmtree(ctx.output_dir)

    isolated_solvers.solvers.register(
        fake_adapter("fake_solver", category=category, cleanup=_cleanup)
    )
    isolated_solvers.extractors.register(
        type("_FakeExtractorOfTheTest", (_FakeExtractor,), {"extract_calls": []})
    )
    monkeypatch.setattr(
        "hydromodpy.results.derive.catchment_aggregation.aggregate_catchment_timeseries",
        lambda sim_id, store, **kwargs: None,
    )
    return registered


class TestPostRunResults:
    def test_store_disabled_noop(self, store, tmp_path):
        sid = store.sim_id
        config = ResultsConfig(persistence=PersistenceConfig(save_catalog=False))
        ctx = _build_run_context(solver_name="modflow_nwt", solver_output_dir=tmp_path)
        # Should return without doing anything
        post_run_results(
            ctx=ctx,
            sim_id=sid,
            results_config=config,
            store=store,
        )

    def test_unknown_solver_raises(self, store, tmp_path, monkeypatch, isolated_solvers):
        sid = store.sim_id
        config = ResultsConfig()
        # Trigger the "no extractor" path via a run-context solver name no
        # registry holds.
        ctx = _build_run_context(solver_name="custom_solver", solver_output_dir=tmp_path)
        _install_post_run_stubs(monkeypatch, isolated_solvers)
        with pytest.raises(RuntimeError, match="No output adapter"):
            post_run_results(
                ctx=ctx,
                sim_id=sid,
                results_config=config,
                store=store,
            )

    def test_no_output_dir_raises(self, store, monkeypatch, isolated_solvers):
        sid = store.sim_id
        config = ResultsConfig()
        ctx = _build_run_context(solver_name="fake_solver", solver_output_dir=None)
        _install_post_run_stubs(monkeypatch, isolated_solvers)
        with pytest.raises(FileNotFoundError, match="Solver output directory is missing"):
            post_run_results(
                ctx=ctx,
                sim_id=sid,
                results_config=config,
                store=store,
            )

    def test_cleanup_when_keep_false(self, store, tmp_path, monkeypatch, isolated_solvers):
        sid = store.sim_id

        solver_dir = tmp_path / "solver_out"
        solver_dir.mkdir()
        (solver_dir / "model.hds").write_text("head data")

        config = ResultsConfig(keep_solver_files=False)
        ctx = _build_run_context(solver_name="fake_solver", solver_output_dir=solver_dir)
        registered = _install_post_run_stubs(monkeypatch, isolated_solvers)
        post_run_results(
            ctx=ctx,
            sim_id=sid,
            results_config=config,
            store=store,
        )
        assert not solver_dir.exists()
        assert registered.cleanup_calls == [ctx]

    def test_keep_solver_files(self, store, tmp_path, monkeypatch, isolated_solvers):
        sid = store.sim_id

        solver_dir = tmp_path / "solver_out"
        solver_dir.mkdir()
        (solver_dir / "model.hds").write_text("head data")

        config = ResultsConfig(keep_solver_files=True)
        ctx = _build_run_context(solver_name="fake_solver", solver_output_dir=solver_dir)
        registered = _install_post_run_stubs(monkeypatch, isolated_solvers)
        post_run_results(
            ctx=ctx,
            sim_id=sid,
            results_config=config,
            store=store,
        )
        assert (solver_dir / "model.hds").exists()
        assert registered.cleanup_calls == []

    def test_lumped_backend_skips_catchment_aggregation(
        self, store, tmp_path, monkeypatch, isolated_solvers
    ):
        sid = store.sim_id

        solver_dir = tmp_path / "solver_out"
        solver_dir.mkdir()

        _install_post_run_stubs(monkeypatch, isolated_solvers, category="lumped")

        def _fail_aggregation(sim_id, store, **kwargs):
            raise AssertionError("lumped extractors must not aggregate spatial fields")

        monkeypatch.setattr(
            "hydromodpy.results.derive.catchment_aggregation.aggregate_catchment_timeseries",
            _fail_aggregation,
        )

        config = ResultsConfig(keep_solver_files=True)
        ctx = _build_run_context(solver_name="fake_solver", solver_output_dir=solver_dir)
        post_run_results(
            ctx=ctx,
            sim_id=sid,
            results_config=config,
            store=store,
        )
