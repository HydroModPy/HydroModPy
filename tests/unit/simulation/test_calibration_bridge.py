"""Tests for simulation/results/calibration_bridge.py."""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from hydromodpy.simulation.results.calibration_bridge import (
    make_hot_simulator,
    persist_calibration_result,
)
from hydromodpy.simulation.results.store import ResultStore


@pytest.fixture
def store(tmp_path):
    project = tmp_path / "project"
    s = ResultStore(project)
    yield s
    s.close()


def _dummy_run_fn(**params):
    """Simulate a simple run returning time series."""
    k = params.get("K", 1.0)
    idx = pd.date_range("2020-01-01", periods=10, freq="D")
    q = pd.Series(np.arange(10, dtype=float) * k, index=idx)
    h = pd.Series(np.linspace(5.0, 3.0, 10) / k, index=idx)
    return {
        "outlet_discharge": q,
        "P1_head": h,
    }


class TestMakeHotSimulator:
    def test_returns_aligned_vector(self):
        obs_plan = [
            ("outlet", "discharge", pd.date_range("2020-01-01", periods=5, freq="D").tolist()),
            ("P1", "head", pd.date_range("2020-01-03", periods=3, freq="D").tolist()),
        ]
        simulator = make_hot_simulator(_dummy_run_fn, obs_plan)
        result = simulator(K=2.0)

        assert isinstance(result, np.ndarray)
        assert result.ndim == 1
        # 5 discharge + 3 head = 8
        assert len(result) == 8

    def test_no_disk_io(self, tmp_path):
        """The hot simulator should not create any files."""
        obs_plan = [
            ("outlet", "discharge", pd.date_range("2020-01-01", periods=3, freq="D").tolist()),
        ]
        simulator = make_hot_simulator(_dummy_run_fn, obs_plan)

        initial_files = set(tmp_path.rglob("*"))
        simulator(K=1.0)
        final_files = set(tmp_path.rglob("*"))

        assert initial_files == final_files

    def test_different_params_different_results(self):
        obs_plan = [
            ("outlet", "discharge", pd.date_range("2020-01-01", periods=5, freq="D").tolist()),
        ]
        simulator = make_hot_simulator(_dummy_run_fn, obs_plan)

        v1 = simulator(K=1.0)
        v2 = simulator(K=2.0)
        assert not np.allclose(v1, v2)


class TestPersistCalibrationResult:
    def test_writes_to_store(self, store):
        sid = str(uuid4())
        obs_plan = [
            ("outlet", "discharge", pd.date_range("2020-01-01", periods=10, freq="D").tolist()),
        ]

        persist_calibration_result(
            store=store,
            sim_id=sid,
            run_fn=_dummy_run_fn,
            best_params={"K": 1.5},
            observation_plan=obs_plan,
            solver="gr4j",
            name="best_run",
        )

        # Verify the simulation was registered and finalized
        sims = store.list_simulations(sim_id=sid)
        assert len(sims) == 1
        assert sims.iloc[0]["status"] == "calibrated"
        assert sims.iloc[0]["name"] == "best_run"

        # Verify timeseries was written
        ts = store.query_timeseries(sid, "outlet", "discharge")
        assert len(ts) == 10
        expected = np.arange(10, dtype=float) * 1.5
        np.testing.assert_array_almost_equal(ts.values, expected)

    def test_persist_multiple_stations(self, store):
        sid = str(uuid4())
        obs_plan = [
            ("outlet", "discharge", pd.date_range("2020-01-01", periods=10, freq="D").tolist()),
            ("P1", "head", pd.date_range("2020-01-01", periods=10, freq="D").tolist()),
        ]

        persist_calibration_result(
            store=store,
            sim_id=sid,
            run_fn=_dummy_run_fn,
            best_params={"K": 1.0},
            observation_plan=obs_plan,
            solver="gr4j",
        )

        ts_q = store.query_timeseries(sid, "outlet", "discharge")
        ts_h = store.query_timeseries(sid, "P1", "head")
        assert len(ts_q) == 10
        assert len(ts_h) == 10
