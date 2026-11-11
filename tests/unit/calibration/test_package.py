"""Tests of `<init>`."""

from __future__ import annotations

import dataclasses
import importlib.util
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pytest

from hydromodpy.calibration.report import (
    FrozenParameter,
    PhaseRun,
    promotion_failures,
    unfinished_session,
)
from hydromodpy.core.state.run_state import ExecutionRegistry
from hydromodpy.results.errors import SeveralCasesError
from hydromodpy.results.metric_rule import PeriodWindow
from hydromodpy.results.session.descriptor import BestCase, BestTrial, read_session
from hydromodpy.results.session.summary import session_summary
from hydromodpy.results.session.view import TRIAL_COLUMNS, Session
from hydromodpy.results.storage.contract import TABLES_DIRNAME
from hydromodpy.results.storage.parquet_io import write_table_atomic
from hydromodpy.results.storage.parquet_schemas import PARQUET_SCHEMA_VERSION
from hydromodpy.solver.base.plan import RunContext
from tests.unit.calibration._factories_runners import make_report, make_session

_WINDOW = PeriodWindow(role="calibration", start=date(2000, 1, 1), end=date(2000, 12, 31))

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
            ({"reused_from_disk": ("a", "b")}, "reused_from_disk", ["a", "b"]),
            ({"methods_path": Path("s/methods.md")}, "methods_path", "s/methods.md"),
            ({"windows": {"fit": _WINDOW}}, "windows", {"fit": _WINDOW.model_dump(mode="json")}),
        ],
        ids=[
            "workspace_when_set",
            "duration_to_three_decimals",
            "best_trial",
            "reused_phases",
            "methods_file",
            "windows",
        ],
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


# -- what a phase, a frozen value and a session on disk say of themselves ------
_FROZEN = FrozenParameter(
    parameter=SimpleNamespace(name="K", effective_path="flow.K", mode="scale"), value=2, phase="p1"
)


def test_a_frozen_value_names_its_path_mode_and_phase() -> None:
    assert _FROZEN.to_dict() == {
        "name": "K",
        "path": "flow.K",
        "value": 2.0,
        "mode": "scale",
        "phase": "p1",
    }


def test_a_phase_says_why_it_stopped_and_which_values_it_moved_again() -> None:
    phase = PhaseRun(
        name="sy",
        index=2,
        session_id="s",
        report=make_report(),
        frozen=(),
        reopened=(_FROZEN,),
        stop_note="froze the best of a budget-only search",
    )

    summary = phase.to_dict()

    assert summary["stop_note"] == "froze the best of a budget-only search"
    assert summary["reopened"] == [_FROZEN.to_dict()]
    assert "stop_note" not in dataclasses.replace(phase, stop_note=None, reopened=()).to_dict()


def test_a_report_without_session_folder_reads_no_run() -> None:
    report = make_report()

    assert report.best_by_case == {}
    assert report.best is None


def test_the_promotion_failures_of_phases_come_before_those_of_the_whole() -> None:
    phase = PhaseRun(
        name="k",
        index=1,
        session_id="s",
        report=make_report(extra={"promotion_failures": ["disk full"]}),
        frozen=(),
    )
    report = make_report(phases=(phase,), extra={"promotion_failures": ["no run"]})

    assert promotion_failures(report) == ["phase k: disk full", "no run"]
    assert promotion_failures(report.to_dict()) == ["phase k: disk full", "no run"]
    assert promotion_failures("nothing") == []
    assert promotion_failures({"extra": None}) == []


def test_a_session_closed_short_of_completed_is_told_with_its_reason(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    session.finalize_session(status="failed", best=None, error="solver died")
    report = make_report(session_dir=session.directory)

    assert unfinished_session(report) == "Session calage closed failed: solver died"
    assert unfinished_session(make_report()) is None
    assert unfinished_session(make_report(session_dir=tmp_path / "none")) is None
    session.finalize_session(status="completed", best=None)
    assert unfinished_session(report.to_dict()) is None


@pytest.mark.parametrize("variable", ["discharge", "lake_level"])
def test_the_summary_names_the_calibrated_variable_and_the_descriptor_the_promoted_run(
    tmp_path: Path, variable: str
) -> None:
    session = make_session(tmp_path)
    (session.directory / "config.toml").write_text(f'[calibration]\nvariable = "{variable}"\n')
    case = BestCase(sim_id="r1", rel_dir="runs/r1", cost=0.1)
    session.set_best(BestTrial(trial=1, cost=0.1, parameters={"K": 1e-4}, cases={"calage": case}))

    summary = session_summary(Session(session.directory))
    run = read_session(session.directory).only_run

    assert (summary.calibrated_variable, run.sim_id, run.rel_dir) == (variable, "r1", "runs/r1")


def test_a_session_without_frozen_config_or_variable_reads_the_discharge(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    assert session_summary(Session(session.directory)).calibrated_variable == "discharge"

    (session.directory / "config.toml").write_text("[flow]\n")
    assert session_summary(Session(session.directory)).calibrated_variable == "discharge"
