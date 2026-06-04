from __future__ import annotations

from hydromodpy.results.run import Run

from ._test_simulation_api_builders import _register, catalog

__all__ = ["catalog"]


class TestSimulationRepr:
    def test_repr_found(self, catalog):
        sid = _register(catalog)
        sim = Run(sid, catalog)
        r = repr(sim)
        assert "test" in r
        assert "modflow6" in r

    def test_repr_not_found(self, catalog):
        sim = Run("nope", catalog)
        r = repr(sim)
        assert "not found" in r
