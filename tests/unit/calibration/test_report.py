"""Calibration report returned by `Project.calibrate`, and the session it summarizes.

The report holds the summary of a search (cost, number of trials, duration in
seconds), the run of each best case, its phases and the trial frame. The lumped
GR4J package it once announced no longer exists.
"""

from __future__ import annotations

import dataclasses
import importlib.util
from datetime import date
from pathlib import Path
from types import SimpleNamespace

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
from hydromodpy.solver.base.plan import RunContext
from tests.unit.calibration._factories_runners import make_report, make_session

WINDOW = PeriodWindow(role="calibration", start=date(2000, 1, 1), end=date(2000, 12, 31))
FROZEN = FrozenParameter(
    parameter=SimpleNamespace(name="K", effective_path="flow.K", mode="scale"), value=2, phase="p1"
)

TO_DICT = [
    pytest.param({"workspace": "ws"}, "workspace", "ws", id="workspace when set"),
    pytest.param(
        {"duration_s": 1.2345678}, "duration_s", pytest.approx(1.235), id="duration to 3 decimals"
    ),
    pytest.param({"best_trial": 4}, "best_trial", 4, id="best trial"),
    pytest.param({"reused_from_disk": ("a", "b")}, "reused_from_disk", ["a", "b"], id="reused"),
    pytest.param(
        {"methods_path": Path("s/methods.md")}, "methods_path", "s/methods.md", id="methods"
    ),
    pytest.param(
        {"windows": {"fit": WINDOW}},
        "windows",
        {"fit": WINDOW.model_dump(mode="json")},
        id="windows",
    ),
]


def test_report_round_trips_to_dict() -> None:
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


@pytest.mark.parametrize(("fields", "key", "expected"), TO_DICT)
def test_to_dict_carries(fields, key, expected) -> None:
    assert make_report(**fields).to_dict()[key] == expected


def test_trial_frame_without_a_session_dir() -> None:
    trials = make_report().trials

    assert len(trials) == 0
    assert tuple(trials.columns) == TRIAL_COLUMNS


def test_report_without_session_folder_reads_no_run() -> None:
    report = make_report()

    assert report.best_by_case == {}
    assert report.best is None


def test_report_of_several_cases() -> None:
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


def test_phase_summary() -> None:
    phase = PhaseRun(
        name="sy",
        index=2,
        session_id="s",
        report=make_report(),
        frozen=(),
        reopened=(FROZEN,),
        stop_note="froze the best of a budget-only search",
    )

    summary = phase.to_dict()

    assert summary["stop_note"] == "froze the best of a budget-only search"
    assert summary["reopened"] == [FROZEN.to_dict()]
    assert "stop_note" not in dataclasses.replace(phase, stop_note=None, reopened=()).to_dict()


def test_promotion_failures_list_phases_first() -> None:
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


def test_unfinished_session(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    session.finalize_session(status="failed", best=None, error="solver died")
    report = make_report(session_dir=session.directory)

    assert unfinished_session(report) == "Session calage closed failed: solver died"
    assert unfinished_session(make_report()) is None
    assert unfinished_session(make_report(session_dir=tmp_path / "none")) is None
    session.finalize_session(status="completed", best=None)
    assert unfinished_session(report.to_dict()) is None


@pytest.mark.parametrize("variable", ["discharge", "lake_level"])
def test_session_summary(tmp_path: Path, variable: str) -> None:
    session = make_session(tmp_path)
    (session.directory / "config.toml").write_text(f'[calibration]\nvariable = "{variable}"\n')
    case = BestCase(sim_id="r1", rel_dir="runs/r1", cost=0.1)
    session.set_best(BestTrial(trial=1, cost=0.1, parameters={"K": 1e-4}, cases={"calage": case}))

    summary = session_summary(Session(session.directory))
    run = read_session(session.directory).only_run

    assert (summary.calibrated_variable, run.sim_id, run.rel_dir) == (variable, "r1", "runs/r1")


def test_lumped_package_is_gone() -> None:
    assert importlib.util.find_spec("hydromodpy.calibration.lumped") is None
    assert "lumped_ram_cache" not in {f.name for f in dataclasses.fields(ExecutionRegistry)}
    assert "lumped_cache" not in {f.name for f in dataclasses.fields(RunContext)}
