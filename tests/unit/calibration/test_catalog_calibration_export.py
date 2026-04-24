"""Tests for the calibration session inspection + export helpers.

Covers Phase 8 of the calibration integration:

- ``catalog.calibration_sessions`` returns a DataFrame with one row per
  session.
- ``catalog.calibration_iterations(session_id)`` returns the iteration
  history as a DataFrame.
- ``catalog.export_calibration_session`` writes
  ``session_manifest.json`` and ``iteration_history.jsonl`` in the
  legacy layout.
"""

from __future__ import annotations

import json
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


class TestExportCalibrationSession:
    def test_writes_manifest_and_jsonl(
        self,
        catalog: SimulationCatalog,
        seeded_session: str,
        tmp_path: Path,
    ):
        out = tmp_path / "export"
        returned = catalog.export_calibration_session(seeded_session, out)
        assert returned == out
        manifest_path = out / "session_manifest.json"
        jsonl_path = out / "iteration_history.jsonl"
        assert manifest_path.is_file()
        assert jsonl_path.is_file()

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["method"] == "optuna"
        assert manifest["objective_name"] == "nse"
        # session_id is normalised to a string
        assert manifest["session_id"]

        lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3
        first = json.loads(lines[0])
        assert "iteration" in first
        assert "objective_value" in first
        assert "parameters" in first

    def test_unknown_session_raises(self, catalog: SimulationCatalog, tmp_path: Path):
        with pytest.raises(ValueError, match="Unknown calibration session"):
            catalog.export_calibration_session(uuid.uuid4().hex, tmp_path / "x")
