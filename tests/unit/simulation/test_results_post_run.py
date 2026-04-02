"""Tests for simulation/results/post_run.py — post-run hook."""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pytest

from hydromodpy.simulation.results.config import ResultsConfig
from hydromodpy.simulation.results.post_run import post_run_results
from hydromodpy.simulation.results.store import ResultStore


@pytest.fixture
def store(tmp_path):
    project = tmp_path / "project"
    s = ResultStore(project)
    yield s
    s.close()


class TestPostRunResults:
    def test_store_disabled_noop(self, store, tmp_path):
        sid = str(uuid4())
        store.register_simulation(sid, solver="modflownwt")
        config = ResultsConfig(store=False)
        # Should return without doing anything
        post_run_results(
            sim_id=sid,
            solver_name="modflownwt",
            solver_output_dir=tmp_path,
            results_config=config,
            store=store,
        )

    def test_unknown_solver_skips(self, store, tmp_path):
        sid = str(uuid4())
        store.register_simulation(sid, solver="custom_solver")
        config = ResultsConfig()
        # Should not raise for unknown solver
        post_run_results(
            sim_id=sid,
            solver_name="custom_solver",
            solver_output_dir=tmp_path,
            results_config=config,
            store=store,
        )

    def test_gr4j_no_output_dir(self, store):
        sid = str(uuid4())
        store.register_simulation(sid, solver="gr4j")
        config = ResultsConfig()
        # GR4J has no solver output dir
        post_run_results(
            sim_id=sid,
            solver_name="gr4j",
            solver_output_dir=None,
            results_config=config,
            store=store,
        )

    def test_cleanup_when_keep_false(self, store, tmp_path):
        sid = str(uuid4())
        store.register_simulation(sid, solver="gr4j")

        solver_dir = tmp_path / "solver_out"
        solver_dir.mkdir()
        (solver_dir / "model.hds").write_text("head data")

        config = ResultsConfig(keep_solver_files=False)
        post_run_results(
            sim_id=sid,
            solver_name="gr4j",
            solver_output_dir=solver_dir,
            results_config=config,
            store=store,
        )
        # Solver files should be cleaned up
        assert not solver_dir.exists()

    def test_keep_solver_files(self, store, tmp_path):
        sid = str(uuid4())
        store.register_simulation(sid, solver="gr4j")

        solver_dir = tmp_path / "solver_out"
        solver_dir.mkdir()
        (solver_dir / "model.hds").write_text("head data")

        config = ResultsConfig(keep_solver_files=True)
        post_run_results(
            sim_id=sid,
            solver_name="gr4j",
            solver_output_dir=solver_dir,
            results_config=config,
            store=store,
        )
        # Solver files should remain
        assert (solver_dir / "model.hds").exists()
