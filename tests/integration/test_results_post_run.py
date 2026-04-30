"""Tests for simulation/results/post_run.py - post-run hook."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.simulation.extraction.post_run import post_run_results
from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan
from hydromodpy.simulation.planning.results_config import ResultsConfig


@pytest.fixture
def catalog(tmp_path):
    c = SimulationCatalog(tmp_path / "workspace")
    yield c
    c.close()


def _build_run_context(
    *,
    solver_name: str,
    process_type: str = "flow",
    solver_output_dir: Path | None = None,
) -> RunContext:
    """Build a minimal RunContext for post_run_results tests.

    The state only carries ``execution.output_dirs_by_run_id`` because that is
    the only attribute the ``adapter.cleanup(ctx)`` path consults.
    """
    run = ProcessRun(
        id=f"{process_type}_main::{solver_name}",
        process_id=f"{process_type}_main",
        process_type=process_type,
        solver=solver_name,
    )
    plan = SimulationPlan(name="test", description="test", runs=(run,))
    output_dirs: dict[str, Path] = {}
    if solver_output_dir is not None:
        output_dirs[run.id] = solver_output_dir
    state = SimpleNamespace(execution=SimpleNamespace(output_dirs_by_run_id=output_dirs))
    return RunContext(plan=plan, run=run, state=state)


class TestPostRunResults:
    def test_store_disabled_noop(self, catalog, tmp_path):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflownwt")
        config = ResultsConfig(store=False)
        ctx = _build_run_context(solver_name="modflownwt", solver_output_dir=tmp_path)
        # Should return without doing anything
        post_run_results(
            ctx=ctx,
            sim_id=sid,
            results_config=config,
            store=catalog,
        )

    def test_unknown_solver_skips(self, catalog, tmp_path):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="custom_solver")
        config = ResultsConfig()
        ctx = _build_run_context(solver_name="custom_solver", solver_output_dir=tmp_path)
        # Should not raise for unknown solver
        post_run_results(
            ctx=ctx,
            sim_id=sid,
            results_config=config,
            store=catalog,
        )

    def test_no_output_dir(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflownwt")
        config = ResultsConfig()
        ctx = _build_run_context(solver_name="modflownwt", solver_output_dir=None)
        # No scratch directory recorded for the run: cleanup is a no-op
        post_run_results(
            ctx=ctx,
            sim_id=sid,
            results_config=config,
            store=catalog,
        )

    def test_cleanup_when_keep_false(self, catalog, tmp_path):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflownwt")

        solver_dir = tmp_path / "solver_out"
        solver_dir.mkdir()
        (solver_dir / "model.hds").write_text("head data")

        config = ResultsConfig(keep_solver_files=False)
        ctx = _build_run_context(solver_name="modflownwt", solver_output_dir=solver_dir)
        post_run_results(
            ctx=ctx,
            sim_id=sid,
            results_config=config,
            store=catalog,
        )
        # Solver files should be cleaned up via adapter.cleanup(ctx)
        assert not solver_dir.exists()

    def test_keep_solver_files(self, catalog, tmp_path):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflownwt")

        solver_dir = tmp_path / "solver_out"
        solver_dir.mkdir()
        (solver_dir / "model.hds").write_text("head data")

        config = ResultsConfig(keep_solver_files=True)
        ctx = _build_run_context(solver_name="modflownwt", solver_output_dir=solver_dir)
        post_run_results(
            ctx=ctx,
            sim_id=sid,
            results_config=config,
            store=catalog,
        )
        # Solver files should remain
        assert (solver_dir / "model.hds").exists()
