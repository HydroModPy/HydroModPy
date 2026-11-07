from __future__ import annotations

import pytest

from hydromodpy.results.run import Run
from tests._helpers.run_builders import MISSING_SIM_ID, runs

__all__ = ["runs"]


class TestSimulationMetadata:
    def test_basic_properties(self, runs):
        sid = runs.open("run1", flow_regime="transient").sim_id
        sim = Run(sid, runs.catalog())
        assert sim.sim_id == sid
        assert sim.name == "run1"
        assert sim.project == "test"
        assert sim.solver == "modflow6"
        assert sim.flow_regime == "transient"
        assert sim.status == "completed"

    def test_config_roundtrip(self, runs):
        cfg = {"flow": {"K": 1.5}}
        sid = runs.open(config=cfg).sim_id
        sim = Run(sid, runs.catalog())
        # A sealed configuration names no machine: the project that holds the run anchors it.
        assert sim.config_snapshot == {**cfg, "workspace": {"project_root": str(runs.project_root)}}

    def test_tags(self, runs):
        sid = runs.open(tags=["fast", "test"]).sim_id
        sim = Run(sid, runs.catalog())
        assert sorted(sim.tags) == ["fast", "test"]

    def test_not_found(self, runs):
        runs.open()
        sim = Run(MISSING_SIM_ID, runs.catalog())
        with pytest.raises(KeyError):
            _ = sim.name
