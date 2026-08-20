"""Tests for simulation/results/calibration_bridge.py."""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.simulation.extraction.calibration_bridge import (
    make_hot_simulator,
    persist_calibration_summary_to_store,
    promote_trial,
)


@pytest.fixture
def store(tmp_path):
    s = Catalog(tmp_path / "workspace")
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
        vector, raw = simulator(K=2.0)

        assert isinstance(vector, np.ndarray)
        assert vector.ndim == 1
        # 5 discharge + 3 head = 8
        assert len(vector) == 8
        # The raw results dict is also returned so callers can persist
        # selected series post-calibration.
        assert "outlet_discharge" in raw
        assert "P1_head" in raw

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

        v1, _ = simulator(K=1.0)
        v2, _ = simulator(K=2.0)
        assert not np.allclose(v1, v2)


class TestPromoteTrial:
    def test_writes_to_store(self, store):
        sid = str(uuid4())
        obs_plan = [
            ("outlet", "discharge", pd.date_range("2020-01-01", periods=10, freq="D").tolist()),
        ]

        promote_trial(
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
        assert sims.iloc[0]["status"] == "completed"
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

        promote_trial(
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


class TestPersistCalibrationSummary:
    """Drive the real persist/promote-best-trial path against a real store.

    ``persist_calibration_summary_to_store`` records the optimizer outcome
    (best params, objective, method, iteration count) without re-running the
    solver, then finalizes the simulation so the calibration outcome is durably
    discoverable from the store.
    """

    def _summary_metrics(self, store, sid):
        df = store.sql(
            "SELECT metric_name, value FROM metrics "
            "WHERE sim_id = ? AND station_id = '__calibration__'",
            [sid],
        )
        return dict(zip(df["metric_name"], df["value"], strict=True))

    def _tags(self, store, sid):
        df = store.sql("SELECT tag FROM tags WHERE sim_id = ?", [sid])
        return set(df["tag"])

    def _params(self, store, sid):
        df = store.sql("SELECT param_name, value FROM parameters WHERE sim_id = ?", [sid])
        return dict(zip(df["param_name"], df["value"], strict=True))

    def test_summary_is_finalized_and_durably_recorded(self, store):
        sid = str(uuid4())
        persist_calibration_summary_to_store(
            store,
            sid,
            best_params={"K": 1.5, "S": 0.02},
            best_objective=0.137,
            method="nelder_mead",
            iteration_count=42,
            score_best=0.81,
            solver="gr4j",
            calibration_id="naizin_session_1",
        )

        sims = store.list_simulations(sim_id=sid)
        assert len(sims) == 1
        assert sims.iloc[0]["name"] == "naizin_session_1"
        assert sims.iloc[0]["solver"] == "gr4j"
        # The write runs end-to-end: the simulation is finalized, not left running.
        assert sims.iloc[0]["status"] == "completed"
        # The string method name is recorded as a tag (the DOUBLE params column
        # cannot hold it).
        assert "method:nelder_mead" in self._tags(store, sid)

        m = self._summary_metrics(store, sid)
        assert m["objective_best"] == pytest.approx(0.137)
        assert m["iteration_count"] == pytest.approx(42.0)
        assert m["score_best"] == pytest.approx(0.81)

    def test_calibrated_params_and_numeric_metadata_recorded(self, store):
        sid = str(uuid4())
        persist_calibration_summary_to_store(
            store,
            sid,
            best_params={"K": 0.9, "S": 0.05},
            best_objective=0.5,
            method="differential_evolution",
            iteration_count=7,
            solver="gr4j",
        )

        recorded = self._params(store, sid)
        assert recorded["K"] == pytest.approx(0.9)
        assert recorded["S"] == pytest.approx(0.05)
        # Numeric run metadata travels with the params (DOUBLE-compatible).
        assert recorded["__objective_best__"] == pytest.approx(0.5)
        assert recorded["__iteration_count__"] == pytest.approx(7.0)
        # score_best omitted -> its param key is absent.
        assert "__score_best__" not in recorded
        assert "method:differential_evolution" in self._tags(store, sid)

    def test_requires_a_valid_solver_code(self, store):
        """No solver -> a clear error up front, nothing is registered."""
        sid = str(uuid4())
        with pytest.raises(ValueError, match="requires the calibrated solver"):
            persist_calibration_summary_to_store(
                store,
                sid,
                best_params={"K": 1.0},
                best_objective=0.3,
                method="nelder_mead",
                iteration_count=5,
            )
        assert len(store.list_simulations(sim_id=sid)) == 0
        assert self._summary_metrics(store, sid) == {}

    def test_score_best_omitted_when_none(self, store):
        sid = str(uuid4())
        persist_calibration_summary_to_store(
            store,
            sid,
            best_params={"K": 0.9},
            best_objective=0.5,
            method="differential_evolution",
            iteration_count=7,
            solver="gr4j",
        )

        m = self._summary_metrics(store, sid)
        assert "objective_best" in m
        assert "iteration_count" in m
        assert "score_best" not in m
        # Default name applied when no calibration_id is provided.
        assert store.list_simulations(sim_id=sid).iloc[0]["name"] == "calibration_best"

    def test_promote_best_of_several_trials(self, store):
        """Persist a cohort of trials, promote the minimum-objective one.

        Every trial finalizes; the best is selected by reading the durable
        objective_best metric back from the store, not the in-memory choice.
        """
        trials = {
            str(uuid4()): {"K": 0.5, "objective": 0.42},
            str(uuid4()): {"K": 1.0, "objective": 0.11},  # best
            str(uuid4()): {"K": 2.0, "objective": 0.37},
            str(uuid4()): {"K": 4.0, "objective": 0.88},
        }
        for trial_sid, t in trials.items():
            persist_calibration_summary_to_store(
                store,
                trial_sid,
                best_params={"K": t["K"]},
                best_objective=t["objective"],
                method="random_search",
                iteration_count=10,
                solver="gr4j",
            )
            assert store.list_simulations(sim_id=trial_sid).iloc[0]["status"] == "completed"

        recorded = store.sql(
            "SELECT sim_id, value AS objective FROM metrics "
            "WHERE station_id = '__calibration__' AND metric_name = 'objective_best'"
        )
        assert len(recorded) == len(trials)

        best_row = recorded.loc[recorded["objective"].idxmin()]
        promoted_sid = str(best_row["sim_id"])
        expected_sid = min(trials, key=lambda s: trials[s]["objective"])
        assert promoted_sid == expected_sid
        assert float(best_row["objective"]) == pytest.approx(0.11)
        assert float(best_row["objective"]) == pytest.approx(
            min(t["objective"] for t in trials.values())
        )

        promoted_k = store.sql(
            "SELECT value FROM parameters WHERE sim_id = ? AND param_name = 'K'",
            [promoted_sid],
        )
        assert float(promoted_k.iloc[0]["value"]) == pytest.approx(1.0)

    def test_summary_survives_store_reopen(self, tmp_path):
        """The summary is on disk: a fresh catalog over the same workspace reads it."""
        workspace = tmp_path / "ws"
        sid = str(uuid4())

        store = Catalog(workspace)
        try:
            persist_calibration_summary_to_store(
                store,
                sid,
                best_params={"K": 3.3},
                best_objective=0.05,
                method="cma",
                iteration_count=120,
                score_best=0.95,
                solver="gr4j",
            )
        finally:
            store.close()

        reopened = Catalog(workspace)
        try:
            objective = reopened.sql(
                "SELECT value FROM metrics WHERE sim_id = ? "
                "AND station_id = '__calibration__' AND metric_name = 'objective_best'",
                [sid],
            )
            assert float(objective.iloc[0]["value"]) == pytest.approx(0.05)
            assert reopened.list_simulations(sim_id=sid).iloc[0]["status"] == "completed"
        finally:
            reopened.close()
