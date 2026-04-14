from __future__ import annotations

import uuid

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.simulation import Simulation
from hydromodpy.results.simulation_group import SimulationGroup


@pytest.fixture
def catalog(tmp_path):
    cat = SimulationCatalog(tmp_path / "workspace")
    yield cat
    cat.close()


def _sid():
    return str(uuid.uuid4())


def _register(catalog, sim_id=None, **kw):
    sid = sim_id or _sid()
    defaults = dict(project="test", solver="modflow6", n_cells=10, n_layers=2)
    defaults.update(kw)
    sz = catalog.register_simulation(sid, **defaults)
    if sz:
        sz.close()
    return sid


def _populate(catalog, sid):
    catalog.write_parameters(sid, [
        {"param_name": "K", "value": 1.5, "unit": "m/d"},
        {"param_name": "Sy", "value": 0.05, "unit": "-"},
    ])
    idx = pd.date_range("2020-01-01", periods=10, freq="D")
    catalog.write_timeseries(sid, "P01", "head", pd.Series(np.arange(10.0), index=idx))
    catalog.write_budget(sid, 0, "z1", "recharge", 100.0, 0.0)
    catalog.write_mass_balance(sid, 0, 100.0, 95.0, 5.0)
    catalog.write_metric(sid, "P01", "nse", 0.85)
    catalog.write_metric(sid, "P01", "kge", 0.78)
    catalog.finalize(sid, "completed", 42.0)


# ============================================================================
# Simulation class tests
# ============================================================================


class TestSimulationMetadata:
    def test_basic_properties(self, catalog):
        sid = _register(catalog, name="run1", flow_regime="transient")
        sim = Simulation(sid, catalog)
        assert sim.id == sid
        assert sim.name == "run1"
        assert sim.project == "test"
        assert sim.solver == "modflow6"
        assert sim.solver_category == "distributed"
        assert sim.flow_regime == "transient"
        assert sim.status == "running"

    def test_config_roundtrip(self, catalog):
        cfg = {"flow": {"K": 1.5}}
        sid = _register(catalog, config=cfg)
        sim = Simulation(sid, catalog)
        assert sim.config == cfg

    def test_tags(self, catalog):
        sid = _register(catalog, tags=["fast", "test"])
        sim = Simulation(sid, catalog)
        assert sim.tags == ["fast", "test"]

    def test_not_found(self, catalog):
        sim = Simulation("nonexistent-uuid", catalog)
        with pytest.raises(KeyError):
            _ = sim.name


class TestSimulationData:
    def test_parameters(self, catalog):
        sid = _register(catalog)
        _populate(catalog, sid)
        sim = Simulation(sid, catalog)
        df = sim.parameters
        assert len(df) == 2
        assert set(df["param_name"]) == {"K", "Sy"}

    def test_metrics(self, catalog):
        sid = _register(catalog)
        _populate(catalog, sid)
        sim = Simulation(sid, catalog)
        df = sim.metrics
        assert len(df) == 2

    def test_timeseries(self, catalog):
        sid = _register(catalog)
        _populate(catalog, sid)
        sim = Simulation(sid, catalog)
        ts = sim.timeseries("head", station="P01")
        assert len(ts) == 10

    def test_timeseries_not_found(self, catalog):
        sid = _register(catalog)
        sim = Simulation(sid, catalog)
        with pytest.raises(KeyError):
            sim.timeseries("head", station="NOPE")

    def test_budget(self, catalog):
        sid = _register(catalog)
        _populate(catalog, sid)
        sim = Simulation(sid, catalog)
        df = sim.budget(component="recharge")
        assert len(df) == 1

    def test_mass_balance(self, catalog):
        sid = _register(catalog)
        _populate(catalog, sid)
        sim = Simulation(sid, catalog)
        df = sim.mass_balance
        assert len(df) == 1

    def test_provenance(self, catalog):
        sid = _register(catalog)
        catalog.write_provenance(sid, "dem", "dem.tif", np.ones(10))
        sim = Simulation(sid, catalog)
        df = sim.provenance
        assert len(df) == 1


class TestSimulationField:
    def test_read_field(self, catalog):
        sid = _register(catalog, n_cells=20, n_layers=2, n_timesteps=3)
        sz = catalog.open_zarr(sid)
        for t in range(3):
            sz.write_field("head", t, np.ones((2, 20)), n_timesteps=3 if t == 0 else None)
        sim = Simulation(sid, catalog)
        result = sim.field("head", timestep=1)
        assert result.shape == (2, 20)

    def test_negative_timestep(self, catalog):
        sid = _register(catalog, n_cells=5, n_layers=1, n_timesteps=4)
        sz = catalog.open_zarr(sid)
        for t in range(4):
            vals = np.full(5, float(t))
            sz.write_field("head", t, vals, n_timesteps=4 if t == 0 else None)
        sim = Simulation(sid, catalog)
        result = sim.field("head", timestep=-1)
        np.testing.assert_array_equal(result, np.full(5, 3.0))


class TestSimulationDisplayCapabilities:
    def test_basic_caps(self, catalog):
        sid = _register(catalog, n_cells=10, n_layers=1, flow_regime="steady")
        sim = Simulation(sid, catalog)
        caps = sim.display_capabilities
        assert "watertable_map" in caps
        assert "budget_chart" in caps
        assert "cross_section" not in caps

    def test_multilayer_caps(self, catalog):
        sid = _register(catalog, n_cells=10, n_layers=3, flow_regime="steady")
        sim = Simulation(sid, catalog)
        assert "cross_section" in sim.display_capabilities

    def test_transient_caps(self, catalog):
        sid = _register(catalog, n_cells=10, n_layers=1, flow_regime="transient")
        sim = Simulation(sid, catalog)
        caps = sim.display_capabilities
        assert "streamflow" in caps
        assert "head_timeseries" in caps


class TestSimulationRepr:
    def test_repr_found(self, catalog):
        sid = _register(catalog)
        sim = Simulation(sid, catalog)
        r = repr(sim)
        assert "test" in r
        assert "modflow6" in r

    def test_repr_not_found(self, catalog):
        sim = Simulation("nope", catalog)
        r = repr(sim)
        assert "not found" in r


# ============================================================================
# SimulationGroup tests
# ============================================================================


class TestSimulationGroup:
    def test_count_and_len(self, catalog):
        sids = [_register(catalog) for _ in range(3)]
        group = SimulationGroup(sids, catalog)
        assert group.count == 3
        assert len(group) == 3

    def test_iter(self, catalog):
        sids = [_register(catalog) for _ in range(2)]
        group = SimulationGroup(sids, catalog)
        sims = list(group)
        assert len(sims) == 2
        assert all(isinstance(s, Simulation) for s in sims)

    def test_getitem(self, catalog):
        sids = [_register(catalog) for _ in range(3)]
        group = SimulationGroup(sids, catalog)
        sim = group[1]
        assert isinstance(sim, Simulation)
        assert sim.id == sids[1]

    def test_best_worst(self, catalog):
        s1 = _register(catalog)
        s2 = _register(catalog)
        catalog.write_metric(s1, "P01", "nse", 0.6)
        catalog.write_metric(s2, "P01", "nse", 0.9)
        catalog.finalize(s1, "completed")
        catalog.finalize(s2, "completed")

        group = SimulationGroup([s1, s2], catalog)
        assert group.best("nse").id == s2
        assert group.worst("nse").id == s1

    def test_sort_by(self, catalog):
        s1 = _register(catalog)
        s2 = _register(catalog)
        s3 = _register(catalog)
        catalog.write_metric(s1, "P01", "nse", 0.5)
        catalog.write_metric(s2, "P01", "nse", 0.9)
        catalog.write_metric(s3, "P01", "nse", 0.7)

        group = SimulationGroup([s1, s2, s3], catalog)
        sorted_g = group.sort_by("nse", ascending=False)
        assert sorted_g.sim_ids[0] == s2
        assert sorted_g.sim_ids[-1] == s1

    def test_compare(self, catalog):
        s1 = _register(catalog)
        s2 = _register(catalog)
        catalog.write_metric(s1, "P01", "nse", 0.6)
        catalog.write_metric(s2, "P01", "nse", 0.9)

        group = SimulationGroup([s1, s2], catalog)
        df = group.compare("nse")
        assert len(df) == 2

    def test_to_dataframe(self, catalog):
        s1 = _register(catalog)
        _populate(catalog, s1)
        s2 = _register(catalog)
        _populate(catalog, s2)

        group = SimulationGroup([s1, s2], catalog)
        df = group.to_dataframe()
        assert len(df) == 2
        assert "sim_id" in df.columns

    def test_empty_group(self, catalog):
        group = SimulationGroup([], catalog)
        assert group.count == 0
        assert group.parameters.empty
        assert group.metrics.empty
        assert group.to_dataframe().empty


# ============================================================================
# Catalog query methods tests
# ============================================================================


class TestCatalogQueryMethods:
    def test_simulations_property(self, catalog):
        _register(catalog, project="a")
        _register(catalog, project="b")
        df = catalog.simulations
        assert len(df) == 2

    def test_getitem(self, catalog):
        sid = _register(catalog)
        sim = catalog[sid]
        assert isinstance(sim, Simulation)
        assert sim.id == sid

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
        assert sim.id == s2

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
        assert sim.id == s2

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


class TestHmpOpen:
    def test_open_returns_catalog(self, tmp_path):
        import hydromodpy as hmp

        cat = hmp.open(tmp_path / "ws")
        assert isinstance(cat, SimulationCatalog)
        cat.close()

    def test_open_roundtrip(self, tmp_path):
        import hydromodpy as hmp

        with hmp.open(tmp_path / "ws") as cat:
            cat.register_simulation(
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "test", "modflow6",
            )
        with hmp.open(tmp_path / "ws") as cat:
            df = cat.simulations
            assert len(df) == 1
