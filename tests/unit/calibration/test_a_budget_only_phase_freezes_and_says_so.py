"""A phase freezes what it found when its search settled, and says how.

The rule, once (:func:`hydromodpy.calibration.optim.stopping.settled`): a phase
passes its values on when its engine met its rule or exhausted its plan. An
engine with no rule of its own (a random search) that spent its budget also
passes them on, and the phase descriptor, ``session.json`` and the console say
"froze the best of a budget-only search". An engine with a rule that the
budget stopped first passes nothing on, and a phase that depends on it is
refused.

No solver runs: a toy configuration and a closed-form metric score each
trial, so the real engines and the real staged runner are under test.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners import staged_runner
from hydromodpy.calibration.runners.staged_runner import (
    _frozen_by,
    _require_result_for_dependents,
    run_staged_calibration,
)
from hydromodpy.cli.commands.calibrate import _format_staged_calibration_result
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.results.checks import BUDGET_RULE, FROZE_BUDGET_ONLY
from hydromodpy.results.session.descriptor import read_session
from hydromodpy.results.session.phase import read_phase
from tests.unit.calibration.test_a_phase_moves_again_what_an_earlier_one_passed import (
    ToyPipeline,
)

RANDOM_THEN_GRID = """
[calibration]
method = "grid"
max_trials = 5
seed = 7
use_cache = false
save_runs = "none"

[calibration.parameters.K]
bounds = [1e-9, 1e-3]
search_space = "log"
target = "flow.param.K.field.value"

[calibration.parameters.Sy]
bounds = [0.001, 0.3]
target = "flow.param.Sy.field.value"

[calibration.outputs.q]
variable = "discharge"
support = "boundary"
boundary_id = "outlet"
observed_values = [1.0, 2.0]

[[calibration.objective_blocks]]
name = "q_block"
metric = "rmse"
uses_outputs = ["q"]

[[calibration.phases]]
name = "coarse"
method = "random_search"
max_trials = 6
parameters = ["K"]
objective_blocks = ["q_block"]

[[calibration.phases]]
name = "storage"
method = "grid"
max_trials = 5
depends_on = "coarse"
parameters = ["Sy"]
objective_blocks = ["q_block"]
"""


@pytest.fixture
def toy(monkeypatch) -> ToyPipeline:
    pipeline = ToyPipeline()
    monkeypatch.setattr(staged_runner, "prepare_trials", pipeline.prepare_trials)
    return pipeline


def test_a_random_search_first_phase_feeds_the_second_and_says_so(
    tmp_path: Path, toy: ToyPipeline, caplog
) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(RANDOM_THEN_GRID, encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        report = run_staged_calibration(path, metric_fn=toy.metric)

    coarse, storage = report.phases
    passed = coarse.report.best_parameters["K"]
    assert coarse.report.extra["search"]["stop_state"] == "budget_spent"
    assert coarse.report.extra["search"]["converged"] is False
    assert [item.name for item in coarse.frozen] == ["K"]
    assert coarse.stop_note == FROZE_BUDGET_ONLY
    assert storage.stop_note is None
    # Every trial of the second phase holds K at the value the first one found.
    held = [k for index, k, _ in toy.trials if index == 1]
    assert held == pytest.approx([passed] * 5)
    assert "Phase coarse froze the best of a budget-only search" in caplog.text

    session_dir = report.session_dir
    assert read_phase(session_dir, "coarse").stop_note == FROZE_BUDGET_ONLY
    assert read_phase(session_dir, "coarse").stop_state == "budget_spent"
    assert read_phase(session_dir, "storage").stop_state == "plan_exhausted"
    descriptor = read_session(session_dir)
    assert descriptor.status == "completed"
    assert descriptor.stop_state == "plan_exhausted"
    assert descriptor.stop_note == f"phase coarse {FROZE_BUDGET_ONLY}"

    lines = _format_staged_calibration_result(report)
    assert f"  {FROZE_BUDGET_ONLY}" in lines
    assert lines.index(f"  {FROZE_BUDGET_ONLY}") < lines.index("phase storage:")


def _space() -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="K", lower=1.0, upper=1.0e3, search_space="log")])


def _report(stop_state: str, rule: str) -> CalibrationReport:
    return CalibrationReport(
        session_id="s1",
        method="random_search",
        n_iterations=20,
        best_objective=0.3,
        best_sim_id=None,
        duration_s=1.0,
        save_runs="none",
        promoted=0,
        best_parameters={"K": 20.0},
        extra={
            "search": {
                "stop_state": stop_state,
                "converged": stop_state != "budget_spent",
                "stopping_rule": rule,
                "max_trials": 20,
                "extension": 0,
                "n_evaluations": 20,
            }
        },
    )


DECL = SimpleNamespace(name="coarse", freeze_on_success=True, parameters=("K",))
DEPENDENT = [SimpleNamespace(decl=SimpleNamespace(name="fine", depends_on="coarse"))]


def test_a_budget_only_search_that_spent_its_budget_freezes_its_best(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        froze = _frozen_by(DECL, _report("budget_spent", BUDGET_RULE), _space())

    assert [(item.name, item.value) for item in froze] == [("K", 20.0)]
    assert FROZE_BUDGET_ONLY in caplog.text
    _require_result_for_dependents(DECL, _report("budget_spent", BUDGET_RULE), DEPENDENT)


@pytest.mark.parametrize(
    ("state", "rule"), [("rule_met", "xatol"), ("plan_exhausted", "every grid point")]
)
def test_a_search_that_met_its_rule_or_its_plan_freezes_quietly(state, rule, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        froze = _frozen_by(DECL, _report(state, rule), _space())

    assert [item.name for item in froze] == ["K"]
    assert caplog.text == ""


def test_a_rule_engine_stopped_by_its_budget_freezes_nothing(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        froze = _frozen_by(DECL, _report("budget_spent", "xatol"), _space())

    assert froze == ()
    assert "before its stopping rule (xatol) was met" in caplog.text
    with pytest.raises(CalibrationError, match="freezes what"):
        _require_result_for_dependents(DECL, _report("budget_spent", "xatol"), DEPENDENT)
