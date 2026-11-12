"""Tests of the stop flag of `optim.engine`: read before each ask, never inside a batch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.core.runtime.interrupts import StopRequested
from tests.unit.calibration._factories_search import make_space

STOP_AT = "2026-11-10T09:30:00+00:00"


def _cost_is_x(sugg: ParamSuggestion) -> EvaluationResult:
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=f"sim-{sugg.trial_id}",
        cost=float(sugg.values["x"]),
        status="completed",
    )


def _flag(directory: Path, text: str | None = None) -> Path:
    path = directory / ".hmp" / "stop.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        text if text is not None else json.dumps({"schema": "hydromodpy.stop.v1", "at": STOP_AT}),
        encoding="utf-8",
    )
    return path


def _engine(flag: Path | None, *, seen: list[int], batch_size: int = 1, **options):
    space = make_space(("x", 0.0, 1.0))

    def evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        seen.append(sugg.trial_id)
        return _cost_is_x(sugg)

    return CalibrationEngine(
        space=space,
        optimizer=build_optimizer("grid", space, points_per_dim=6),
        evaluator=evaluator,
        max_trials=6,
        batch_size=batch_size,
        stop_flag=flag,
        **options,
    )


@pytest.mark.parametrize(
    ("flag_state", "expected_trials"),
    [
        pytest.param("none", 6, id="no_flag_path"),
        pytest.param("absent", 6, id="flag_path_without_file"),
        pytest.param("present", 0, id="flag_on_disk_before_the_first_ask"),
        pytest.param("unreadable", 0, id="unreadable_flag_still_stops"),
    ],
)
def test_the_flag_is_read_before_the_first_ask(tmp_path, flag_state, expected_trials) -> None:
    flag = tmp_path / ".hmp" / "stop.json"
    if flag_state == "none":
        flag = None
    elif flag_state == "present":
        _flag(tmp_path)
    elif flag_state == "unreadable":
        _flag(tmp_path, "not json")
    seen: list[int] = []
    engine = _engine(flag, seen=seen)

    if expected_trials == 0:
        with pytest.raises(StopRequested):
            engine.run()
    else:
        assert len(engine.run().history) == expected_trials
    assert len(seen) == expected_trials
