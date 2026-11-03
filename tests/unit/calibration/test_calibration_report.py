"""Tests for :class:`hydromodpy.calibration.report.CalibrationReport`.

The structured return type produced by ``run_calibration_cli`` /
``Project.calibrate``: its summary, its names for the run of each case and its
trial frame.
"""

from __future__ import annotations

from typing import Any

import pytest

from hydromodpy.calibration import CalibrationReport
from hydromodpy.results.errors import SeveralCasesError
from hydromodpy.results.session.descriptor import BestCase
from hydromodpy.results.session.view import TRIAL_COLUMNS


def _report(**fields: Any) -> CalibrationReport:
    base = {
        "session_id": "abc",
        "method": "grid",
        "n_trials": 1,
        "best_cost": 0.1,
        "duration_s": 0.0,
        "save_runs": "none",
        "promoted": 0,
    }
    return CalibrationReport(**{**base, **fields})


class TestCalibrationReportBasic:
    def test_fields_stored_and_round_trip_to_dict(self):
        report = _report(
            method="optuna",
            n_trials=100,
            best_cost=0.42,
            duration_s=123.456,
            save_runs="best_n",
            promoted=5,
            best_cases={"case": BestCase(sim_id="deadbeef", rel_dir="runs/calage", cost=0.42)},
        )
        payload = report.to_dict()
        assert payload["session_id"] == "abc"
        assert payload["method"] == "optuna"
        assert payload["n_trials"] == 100
        assert payload["best_cost"] == pytest.approx(0.42)
        assert payload["best_sim_id"] == report.best_sim_id == "deadbeef"
        assert payload["best_rel_dir"] == report.best_rel_dir == "runs/calage"
        assert payload["best_cases"]["case"]["sim_id"] == "deadbeef"
        assert payload["duration_s"] == pytest.approx(123.456)
        assert payload["save_runs"] == "best_n"
        assert payload["promoted"] == 5
        assert "workspace" not in payload
        assert "extra" not in payload

    def test_to_dict_emits_workspace_when_set(self, tmp_path):
        assert _report(workspace=tmp_path).to_dict()["workspace"] == str(tmp_path)

    def test_to_dict_duration_rounded_to_three_decimals(self):
        assert _report(duration_s=1.2345678).to_dict()["duration_s"] == pytest.approx(1.235)

    def test_the_trial_frame_is_empty_without_a_session_dir(self):
        trials = _report().trials

        assert len(trials) == 0
        assert tuple(trials.columns) == TRIAL_COLUMNS

    def test_the_best_trial_is_in_the_payload(self):
        assert _report(best_trial=4).to_dict()["best_trial"] == 4

    def test_a_report_of_no_run_names_none(self):
        report = _report()

        assert (report.best_sim_id, report.best_rel_dir) == (None, None)
        assert report.to_dict()["best_sim_id"] is None

    def test_a_report_of_several_cases_names_each_run_and_refuses_the_one(self):
        report = _report(
            best_cases={
                "a": BestCase(sim_id="1" * 32, rel_dir="runs/a", cost=0.1),
                "b": BestCase(sim_id="2" * 32, rel_dir="runs/b", cost=0.2),
            }
        )

        payload = report.to_dict()
        assert set(payload["best_cases"]) == {"a", "b"}
        assert "best_sim_id" not in payload
        with pytest.raises(SeveralCasesError, match="best_cases"):
            report.best_sim_id  # noqa: B018
