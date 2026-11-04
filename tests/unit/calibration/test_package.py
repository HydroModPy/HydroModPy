"""Tests of `<init>`."""

from __future__ import annotations

import dataclasses
import importlib.util

import pytest

from hydromodpy.core.state.execution import ExecutionRegistry
from hydromodpy.results.errors import SeveralCasesError
from hydromodpy.results.session.descriptor import BestCase
from hydromodpy.results.session.view import TRIAL_COLUMNS
from hydromodpy.simulation.planning.plan import RunContext
from tests.unit.calibration._factories_runners import make_report

# From test_calibration_report.py
# Tests for :class:`hydromodpy.calibration.report.CalibrationReport`.
#
# The structured return type produced by ``run_calibration_cli`` /
# ``Project.calibrate``: its summary, its names for the run of each case and its
# trial frame.


class TestCalibrationReportBasic:
    def test_fields_stored_and_round_trip_to_dict(self):
        report = make_report(
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

    @pytest.mark.parametrize(
        ("fields", "key", "expected"),
        [
            ({"workspace": "ws"}, "workspace", "ws"),
            ({"duration_s": 1.2345678}, "duration_s", pytest.approx(1.235)),
            ({"best_trial": 4}, "best_trial", 4),
        ],
        ids=["workspace_when_set", "duration_to_three_decimals", "best_trial"],
    )
    def test_to_dict_carries(self, fields, key, expected):
        assert make_report(**fields).to_dict()[key] == expected

    def test_the_trial_frame_is_empty_without_a_session_dir(self):
        trials = make_report().trials

        assert len(trials) == 0
        assert tuple(trials.columns) == TRIAL_COLUMNS

    def test_a_report_of_no_run_names_none(self):
        report = make_report()

        assert (report.best_sim_id, report.best_rel_dir) == (None, None)
        assert report.to_dict()["best_sim_id"] is None

    def test_a_report_of_several_cases_names_each_run_and_refuses_the_one(self):
        report = make_report(
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


# From test_the_calibration_package_holds_no_model_less_gr4j.py
# GR4J never had a model in HydroModPy, so the package that announced it is gone.


def test_the_lumped_package_is_not_importable() -> None:
    assert importlib.util.find_spec("hydromodpy.calibration.lumped") is None


def test_no_run_carries_a_lumped_ram_cache() -> None:
    assert "lumped_ram_cache" not in {f.name for f in dataclasses.fields(ExecutionRegistry)}
    assert "lumped_cache" not in {f.name for f in dataclasses.fields(RunContext)}
