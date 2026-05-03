"""Tests for the calibration session inspection views on the catalog.

- ``catalog.calibration_sessions`` returns a DataFrame with one row per
  session.
- ``catalog.calibration_iterations(session_id)`` returns the iteration
  history as a DataFrame.
- ``CalibrationPersistence.append_iteration`` honours the ``detail``
  argument when persisting iteration metrics.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.calibration.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.results.catalog import SimulationCatalog


@pytest.fixture()
def catalog(tmp_path: Path):
    """Open an isolated calibration catalog rooted under tmp_path."""
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    catalog = SimulationCatalog(tmp_path)
    yield catalog
    catalog.close()


@pytest.fixture()
def seeded_session(catalog: SimulationCatalog) -> str:
    """Insert a calibration session with a few iterations; return the sid."""
    persistence = CalibrationPersistence(catalog)
    sid = uuid.uuid4().hex
    persistence.start_session(
        session_id=sid,
        project="unit_test",
        method="optuna",
        objective_name="nse",
        config={"max_iter": 3},
    )
    for i in range(3):
        sugg = ParamSuggestion(
            trial_id=i,
            values={"K": 1e-4 * (i + 1)},
        )
        result = EvaluationResult(
            trial_id=i,
            sim_id=None,
            objective_value=0.5 - 0.1 * i,
            status="completed",
            duration_s=0.1,
            components={"nse": 0.5 - 0.1 * i},
        )
        persistence.append_iteration(sid, sugg, result)
    persistence.finalize_session(
        sid,
        best=EvaluationResult(
            trial_id=2,
            sim_id=None,
            objective_value=0.3,
            status="completed",
        ),
        n_iterations=3,
        duration_s=0.3,
    )
    return sid


class TestCalibrationSessionsDataFrame:
    def test_returns_dataframe(self, catalog: SimulationCatalog, seeded_session: str):
        df = catalog.calibration_sessions
        assert isinstance(df, pd.DataFrame)
        assert len(df) >= 1
        ids = {str(x) for x in df["session_id"].astype(str)}
        # The stored session_id is a UUID - match either the hex or dashed form.
        dashed = str(uuid.UUID(seeded_session))
        assert (
            (seeded_session in ids) or (dashed in ids) or any(seeded_session[:8] in x for x in ids)
        )


class TestCalibrationIterationsDataFrame:
    def test_three_rows(self, catalog: SimulationCatalog, seeded_session: str):
        df = catalog.calibration_iterations(seeded_session)
        assert len(df) == 3
        assert set(df["iteration"]) == {0, 1, 2}
        assert list(df.columns) == [
            "iteration",
            "sim_id",
            "params_hash",
            "parameters",
            "objective_value",
            "metrics",
            "status",
            "from_cache",
            "duration_s",
        ]


class TestPersistIterationDetail:
    def _seed_session(self, catalog: SimulationCatalog) -> str:
        persistence = CalibrationPersistence(catalog)
        sid = uuid.uuid4().hex
        persistence.start_session(
            session_id=sid,
            project="detail_test",
            method="optuna",
            objective_name="rmse",
            config={"max_iter": 1},
        )
        return sid

    def test_persist_iteration_detail_full_writes_block_costs(
        self,
        catalog: SimulationCatalog,
    ):
        sid = self._seed_session(catalog)
        persistence = CalibrationPersistence(catalog)
        sugg = ParamSuggestion(trial_id=0, values={"K": 1e-4})
        result = EvaluationResult(
            trial_id=0,
            sim_id=None,
            objective_value=0.42,
            status="completed",
            duration_s=0.1,
            components={"rmse": 0.42},
            metadata={"block_costs": {"head": 0.5, "discharge": 0.3}},
        )
        persistence.append_iteration(sid, sugg, result, detail="full")
        rows = persistence.load_iterations(sid)
        assert len(rows) == 1
        metrics = rows[0]["metrics"]
        assert metrics is not None
        assert "block_costs" in metrics
        assert metrics["block_costs"] == {"head": 0.5, "discharge": 0.3}

    def test_persist_iteration_detail_none_clears_metrics(
        self,
        catalog: SimulationCatalog,
    ):
        sid = self._seed_session(catalog)
        persistence = CalibrationPersistence(catalog)
        sugg = ParamSuggestion(trial_id=0, values={"K": 1e-4})
        result = EvaluationResult(
            trial_id=0,
            sim_id=None,
            objective_value=0.42,
            status="completed",
            duration_s=0.1,
            components={"rmse": 0.42},
        )
        persistence.append_iteration(sid, sugg, result, detail="none")
        rows = persistence.load_iterations(sid)
        assert len(rows) == 1
        assert rows[0]["metrics"] is None
