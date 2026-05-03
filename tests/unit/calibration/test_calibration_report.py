"""Tests for :class:`hydromodpy.calibration.report.CalibrationReport`.

Covers Phase 6 of the calibration integration: the structured return type
produced by ``run_calibration_cli`` / ``Project.calibrate``.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration import CalibrationReport


class TestCalibrationReportBasic:
    def test_fields_stored_and_round_trip_to_dict(self):
        report = CalibrationReport(
            session_id="abc",
            method="optuna",
            n_iterations=100,
            best_objective=0.42,
            best_sim_id="deadbeef",
            duration_s=123.456,
            save_runs="best_n",
            promoted=5,
        )
        payload = report.to_dict()
        assert payload["session_id"] == "abc"
        assert payload["method"] == "optuna"
        assert payload["n_iterations"] == 100
        assert payload["best_objective"] == pytest.approx(0.42)
        assert payload["best_sim_id"] == "deadbeef"
        assert payload["duration_s"] == pytest.approx(123.456)
        assert payload["save_runs"] == "best_n"
        assert payload["promoted"] == 5
        assert "workspace" not in payload
        assert "extra" not in payload

    def test_to_dict_emits_workspace_when_set(self, tmp_path):
        report = CalibrationReport(
            session_id="abc",
            method="grid",
            n_iterations=1,
            best_objective=None,
            best_sim_id=None,
            duration_s=0.0,
            save_runs="none",
            promoted=0,
            workspace=tmp_path,
        )
        payload = report.to_dict()
        assert payload["workspace"] == str(tmp_path)

    def test_to_dict_duration_rounded_to_three_decimals(self):
        report = CalibrationReport(
            session_id="abc",
            method="grid",
            n_iterations=1,
            best_objective=0.0,
            best_sim_id=None,
            duration_s=1.2345678,
            save_runs="none",
            promoted=0,
        )
        assert report.to_dict()["duration_s"] == pytest.approx(1.235)

    def test_iterations_returns_empty_dataframe_when_no_workspace(self):
        report = CalibrationReport(
            session_id="abc",
            method="grid",
            n_iterations=0,
            best_objective=None,
            best_sim_id=None,
            duration_s=0.0,
            save_runs="none",
            promoted=0,
        )
        df = report.iterations
        assert len(df) == 0

    def test_best_returns_none_when_no_best_sim_id(self):
        report = CalibrationReport(
            session_id="abc",
            method="grid",
            n_iterations=1,
            best_objective=0.1,
            best_sim_id=None,
            duration_s=0.0,
            save_runs="none",
            promoted=0,
        )
        assert report.best is None
