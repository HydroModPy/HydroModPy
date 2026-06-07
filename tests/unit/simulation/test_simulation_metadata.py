from __future__ import annotations

import pytest

from hydromodpy.results.run import Run

from ._test_simulation_api_builders import _register, catalog

__all__ = ["catalog"]


class TestSimulationMetadata:
    def test_basic_properties(self, catalog):
        sid = _register(catalog, name="run1", flow_regime="transient")
        sim = Run(sid, catalog)
        assert sim.sim_id == sid
        assert sim.name == "run1"
        assert sim.project == "test"
        assert sim.solver == "modflow6"
        assert sim.solver_category == "distributed"
        assert sim.flow_regime == "transient"
        assert sim.status == "running"

    def test_config_roundtrip(self, catalog):
        cfg = {"flow": {"K": 1.5}}
        sid = _register(catalog, config=cfg)
        sim = Run(sid, catalog)
        assert sim.config_snapshot == cfg

    def test_tags(self, catalog):
        sid = _register(catalog, tags=["fast", "test"])
        sim = Run(sid, catalog)
        assert sim.tags == ["fast", "test"]

    def test_not_found(self, catalog):
        sim = Run("nonexistent-uuid", catalog)
        with pytest.raises(KeyError):
            _ = sim.name
