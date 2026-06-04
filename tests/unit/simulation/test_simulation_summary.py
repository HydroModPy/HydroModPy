from __future__ import annotations

import json

import pytest

from hydromodpy.results.run import Run

from ._test_simulation_api_builders import _register, catalog

__all__ = ["catalog"]


class TestSimulationSummary:
    def test_dict_keys(self, catalog):
        sid = _register(catalog, name="run1", flow_regime="transient", n_timesteps=12)
        sim = Run(sid, catalog)
        info = sim.summary()
        assert isinstance(info, dict)
        expected = {
            "sim_id",
            "name",
            "project",
            "solver",
            "solver_category",
            "flow_regime",
            "status",
            "created_at",
            "duration_s",
            "n_layers",
            "n_cells",
            "n_timesteps",
            "tags",
        }
        assert set(info) == expected
        assert info["sim_id"] == sid
        assert info["name"] == "run1"
        assert info["project"] == "test"
        assert info["solver"] == "modflow6"
        assert info["flow_regime"] == "transient"
        assert info["n_layers"] == 2
        assert info["n_cells"] == 10
        assert info["n_timesteps"] == 12

    def test_json_roundtrip(self, catalog):
        sid = _register(catalog, name="run-json", tags=["a", "b"])
        catalog.finalize(sid, "completed", 7.5)
        sim = Run(sid, catalog)
        payload = sim.summary(json=True)
        assert isinstance(payload, str)
        parsed = json.loads(payload)
        assert parsed["sim_id"] == sid
        assert parsed["name"] == "run-json"
        assert parsed["status"] == "completed"
        assert parsed["duration_s"] == pytest.approx(7.5)
        assert parsed["tags"] == ["a", "b"]
        # created_at must serialise (datetime -> string)
        assert isinstance(parsed["created_at"], str)

    def test_not_found(self, catalog):
        sim = Run("nonexistent-uuid", catalog)
        with pytest.raises(KeyError):
            sim.summary()
