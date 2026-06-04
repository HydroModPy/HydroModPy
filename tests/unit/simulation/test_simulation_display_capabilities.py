from __future__ import annotations

from hydromodpy.results.run import Run

from ._test_simulation_api_builders import _register, catalog

__all__ = ["catalog"]


class TestSimulationDisplayCapabilities:
    def test_basic_caps(self, catalog):
        sid = _register(catalog, n_cells=10, n_layers=1, flow_regime="steady")
        sim = Run(sid, catalog)
        caps = sim.display_capabilities
        assert "piezometric_map" in caps
        assert "water_budget" in caps
        assert "cross_section" not in caps

    def test_multilayer_caps(self, catalog):
        sid = _register(catalog, n_cells=10, n_layers=3, flow_regime="steady")
        sim = Run(sid, catalog)
        assert "cross_section" in sim.display_capabilities

    def test_transient_caps(self, catalog):
        sid = _register(catalog, n_cells=10, n_layers=1, flow_regime="transient")
        sim = Run(sid, catalog)
        caps = sim.display_capabilities
        assert "hydrograph" in caps
