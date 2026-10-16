from __future__ import annotations

import pytest

from hydromodpy.results.catalog import SimulationNotFoundError
from hydromodpy.results.run import Run
from tests._helpers.sealed_runs import write_attempt

from ._test_simulation_api_builders import runs, score

__all__ = ["runs"]


class TestCatalogQueryMethods:
    def test_simulations_property(self, runs):
        runs.open(project="a")
        runs.open(project="b")
        assert len(runs.catalog().simulations) == 2

    def test_getitem(self, runs):
        sid = runs.open().sim_id
        sim = runs.catalog()[sid]
        assert isinstance(sim, Run)
        assert sim.sim_id == sid

    def test_getitem_not_found(self, runs):
        runs.open()
        with pytest.raises(SimulationNotFoundError):
            _ = runs.catalog()["nonexistent"]

    def test_find_by_project(self, runs):
        runs.open(project="canut")
        runs.open(project="canut")
        runs.open(project="nancon")
        assert runs.catalog().find(project="canut").count == 2

    def test_find_by_solver(self, runs):
        runs.open(solver="modflow6")
        runs.open(solver="boussinesq")
        assert runs.catalog().find(solver="modflow6").count == 1

    def test_find_by_status_sees_sealed_runs_only(self, runs):
        """A failed attempt is a case of the index, never a run: it carries no seal."""
        runs.open()
        write_attempt(runs.project_root, "runs/broken", status="failed")
        catalog = runs.catalog()
        assert catalog.find(status="completed").count == 1
        assert catalog.find(status="failed").count == 0
        assert set(catalog.cases["status"]) == {"completed", "failed"}

    def test_find_by_metric_threshold(self, runs):
        for value in (0.5, 0.8, 0.9):
            score(runs.open(), value)
        assert runs.catalog().find(nse_gt=0.7).count == 2

    def test_find_ignores_a_metric_scored_outside_the_rule(self, runs):
        store = runs.open()
        store.write_metric(store.sim_id, "P01", "nse", 0.95)
        assert runs.catalog().find(nse_gt=0.7).count == 0

    def test_find_combined_filters(self, runs):
        runs.open(project="canut", solver="modflow6")
        runs.open(project="canut", solver="boussinesq")
        runs.open(project="nancon", solver="modflow6")
        assert runs.catalog().find(project="canut", solver="modflow6").count == 1

    def test_find_by_tags(self, runs):
        runs.open(tags=["transient", "test"])
        runs.open(tags=["steady"])
        assert runs.catalog().find(tags="transient").count == 1

    def test_find_unknown_filter(self, runs):
        runs.open()
        with pytest.raises(ValueError, match="Unknown filter"):
            runs.catalog().find(nonexistent_field="x")

    def test_latest(self, runs):
        runs.open(project="p1")
        runs.catalog()
        second = runs.open(project="p1").sim_id
        assert runs.catalog().latest("p1").sim_id == second

    def test_latest_not_found(self, runs):
        runs.open(project="p1")
        with pytest.raises(KeyError):
            runs.catalog().latest("nonexistent")

    def test_best(self, runs):
        low, high = runs.open(project="p1"), runs.open(project="p1")
        score(low, 0.6)
        score(high, 0.9)
        assert runs.catalog().best("p1", metric="nse").sim_id == high.sim_id

    def test_best_not_found(self, runs):
        runs.open(project="p1")
        with pytest.raises(KeyError):
            runs.catalog().best("nonexistent", metric="nse")

    def test_sql(self, runs):
        runs.open(project="p1")
        runs.open(project="p2")
        df = runs.catalog().sql("SELECT project, COUNT(*) as n FROM simulations GROUP BY project")
        assert len(df) == 2
