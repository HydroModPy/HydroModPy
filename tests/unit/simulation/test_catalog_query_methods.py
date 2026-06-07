from __future__ import annotations

import pytest

from hydromodpy.results.run import Run

from ._test_simulation_api_builders import _register, catalog

__all__ = ["catalog"]


class TestCatalogQueryMethods:
    def test_simulations_property(self, catalog):
        _register(catalog, project="a")
        _register(catalog, project="b")
        df = catalog.simulations
        assert len(df) == 2

    def test_getitem(self, catalog):
        sid = _register(catalog)
        sim = catalog[sid]
        assert isinstance(sim, Run)
        assert sim.sim_id == sid

    def test_getitem_not_found(self, catalog):
        with pytest.raises(KeyError):
            _ = catalog["nonexistent"]

    def test_find_by_project(self, catalog):
        _register(catalog, project="canut")
        _register(catalog, project="canut")
        _register(catalog, project="nancon")
        group = catalog.find(project="canut")
        assert group.count == 2

    def test_find_by_solver(self, catalog):
        _register(catalog, solver="modflow6")
        _register(catalog, solver="boussinesq")
        group = catalog.find(solver="modflow6")
        assert group.count == 1

    def test_find_by_status(self, catalog):
        s1 = _register(catalog)
        s2 = _register(catalog)
        catalog.finalize(s1, "completed")
        catalog.finalize(s2, "failed")
        group = catalog.find(status="completed")
        assert group.count == 1

    def test_find_by_metric_threshold(self, catalog):
        s1 = _register(catalog)
        s2 = _register(catalog)
        s3 = _register(catalog)
        catalog.write_metric(s1, "P01", "nse", 0.5)
        catalog.write_metric(s2, "P01", "nse", 0.8)
        catalog.write_metric(s3, "P01", "nse", 0.9)
        group = catalog.find(nse_gt=0.7)
        assert group.count == 2

    def test_find_combined_filters(self, catalog):
        s1 = _register(catalog, project="canut")
        s2 = _register(catalog, project="canut")
        s3 = _register(catalog, project="nancon")
        catalog.finalize(s1, "completed")
        catalog.finalize(s2, "failed")
        catalog.finalize(s3, "completed")
        group = catalog.find(project="canut", status="completed")
        assert group.count == 1

    def test_find_by_tags(self, catalog):
        _register(catalog, tags=["transient", "test"])
        _register(catalog, tags=["steady"])
        group = catalog.find(tags="transient")
        assert group.count == 1

    def test_find_unknown_filter(self, catalog):
        with pytest.raises(ValueError, match="Unknown filter"):
            catalog.find(nonexistent_field="x")

    def test_latest(self, catalog):
        s1 = _register(catalog, project="p1")
        catalog.finalize(s1, "completed")
        s2 = _register(catalog, project="p1")
        catalog.finalize(s2, "completed")
        sim = catalog.latest("p1")
        assert sim.sim_id == s2

    def test_latest_not_found(self, catalog):
        with pytest.raises(KeyError):
            catalog.latest("nonexistent")

    def test_best(self, catalog):
        s1 = _register(catalog, project="p1")
        s2 = _register(catalog, project="p1")
        catalog.write_metric(s1, "P01", "nse", 0.6)
        catalog.write_metric(s2, "P01", "nse", 0.9)
        catalog.finalize(s1, "completed")
        catalog.finalize(s2, "completed")
        sim = catalog.best("p1", metric="nse")
        assert sim.sim_id == s2

    def test_best_not_found(self, catalog):
        with pytest.raises(KeyError):
            catalog.best("nonexistent", metric="nse")

    def test_sql(self, catalog):
        _register(catalog, project="p1")
        _register(catalog, project="p2")
        df = catalog.sql("SELECT project, COUNT(*) as n FROM simulations GROUP BY project")
        assert len(df) == 2

    def test_cleanup_by_status(self, catalog):
        s1 = _register(catalog)
        s2 = _register(catalog)
        catalog.finalize(s1, "completed")
        catalog.finalize(s2, "failed")
        n = catalog.cleanup(status="failed")
        assert n == 1
        assert catalog.simulations.shape[0] == 1
