"""Tests for simulation/results/post_run.py — post-run hook."""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pytest

from hydromodpy.results.config import ResultsConfig
from hydromodpy.simulation.extraction.post_run import post_run_results
from hydromodpy.results.catalog import SimulationCatalog


@pytest.fixture
def catalog(tmp_path):
    c = SimulationCatalog(tmp_path / "workspace")
    yield c
    c.close()


class TestPostRunResults:
    def test_store_disabled_noop(self, catalog, tmp_path):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflownwt")
        config = ResultsConfig(store=False)
        # Should return without doing anything
        post_run_results(
            sim_id=sid,
            solver_name="modflownwt",
            solver_output_dir=tmp_path,
            results_config=config,
            store=catalog,
        )

    def test_unknown_solver_skips(self, catalog, tmp_path):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="custom_solver")
        config = ResultsConfig()
        # Should not raise for unknown solver
        post_run_results(
            sim_id=sid,
            solver_name="custom_solver",
            solver_output_dir=tmp_path,
            results_config=config,
            store=catalog,
        )

    def test_gr4j_no_output_dir(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")
        config = ResultsConfig()
        # GR4J has no solver output dir
        post_run_results(
            sim_id=sid,
            solver_name="gr4j",
            solver_output_dir=None,
            results_config=config,
            store=catalog,
        )

    def test_cleanup_when_keep_false(self, catalog, tmp_path):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")

        solver_dir = tmp_path / "solver_out"
        solver_dir.mkdir()
        (solver_dir / "model.hds").write_text("head data")

        config = ResultsConfig(keep_solver_files=False)
        post_run_results(
            sim_id=sid,
            solver_name="gr4j",
            solver_output_dir=solver_dir,
            results_config=config,
            store=catalog,
        )
        # Solver files should be cleaned up
        assert not solver_dir.exists()

    def test_keep_solver_files(self, catalog, tmp_path):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")

        solver_dir = tmp_path / "solver_out"
        solver_dir.mkdir()
        (solver_dir / "model.hds").write_text("head data")

        config = ResultsConfig(keep_solver_files=True)
        post_run_results(
            sim_id=sid,
            solver_name="gr4j",
            solver_output_dir=solver_dir,
            results_config=config,
            store=catalog,
        )
        # Solver files should remain
        assert (solver_dir / "model.hds").exists()
