from __future__ import annotations

from hydromodpy.results.run import Run
from tests._helpers.run_builders import MISSING_SIM_ID, runs

__all__ = ["runs"]


class TestSimulationRepr:
    def test_repr_found(self, runs):
        sid = runs.open().sim_id
        r = repr(Run(sid, runs.catalog()))
        assert "test" in r
        assert "modflow6" in r

    def test_repr_not_found(self, runs):
        runs.open()
        r = repr(Run(MISSING_SIM_ID, runs.catalog()))
        assert "not found" in r
