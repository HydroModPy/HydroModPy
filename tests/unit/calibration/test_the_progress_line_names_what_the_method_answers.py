"""The live progress line names what the method will answer with.

A root search answers with a root. Its lowest cost is often a trial far from
it: on the Nancon two-bound search, the bar read ``best 71.8`` at K = 1e-7
while the session answered K = 5.9e-6. The line of a root search names its
bracket, then the root, never a minimum cost.
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.optim import progress_reporter
from hydromodpy.calibration.optim.adapters.bisection_adapter import BisectionAdapter
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.progress_reporter import ConsoleProgressReporter
from hydromodpy.calibration.optim.stopping import AUTO_BUDGET

ROOT_MIN = 3.0e-6
ROOT_MAX = 2.0e-4


class _Handle:
    def __init__(self, description: str) -> None:
        self.descriptions = [description]

    def update(self, *, description: str | None = None, **_: object) -> None:
        if description is not None:
            self.descriptions.append(description)

    def advance(self, step: float = 1.0) -> None:
        del step


@pytest.fixture
def handles(monkeypatch) -> list[_Handle]:
    """Record every description the reporter draws, without a console."""
    seen: list[_Handle] = []

    @contextmanager
    def _task(description: str, *, total: float | None = None, unit: str = "it"):
        del total, unit
        handle = _Handle(description)
        seen.append(handle)
        yield handle

    monkeypatch.setattr(progress_reporter, "progress", SimpleNamespace(task=_task))
    return seen


def _space() -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="K", lower=1e-7, upper=1e-3, transform="log")])


def _staircase(root: float, value: float) -> float:
    return (math.floor(math.log10(root / value) * 200.0) + 0.5) / 200.0


def _two_bounds(sugg: ParamSuggestion) -> EvaluationResult:
    """A cost lowest far from the combined root, as on the Nancon."""
    value = float(sugg.values["K"])
    j_min = _staircase(ROOT_MIN, value)
    j_max = _staircase(ROOT_MAX, value)
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=None,
        objective_value=0.5 * abs(j_min) + 0.5 * abs(j_max),
        status="completed",
        components={
            "net.n_bounds_scored": 2.0,
            "net.weight_minimal": 0.5,
            "net.weight_maximal": 0.5,
            "net.J_signed_minimal": j_min,
            "net.J_signed_maximal": j_max,
        },
    )


def _one_bound(sugg: ParamSuggestion) -> EvaluationResult:
    residual = _staircase(ROOT_MAX, float(sugg.values["K"]))
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=None,
        objective_value=abs(residual),
        status="completed",
        components={"net.J_signed": residual},
    )


def _search(adapter: BisectionAdapter, evaluator, reporter):
    return CalibrationEngine(
        space=adapter.space,
        optimizer=adapter,
        evaluator=evaluator,
        max_iter=AUTO_BUDGET,
        progress=reporter,
    ).run()


def test_a_two_root_search_ends_on_the_root_it_returns(handles) -> None:
    adapter = BisectionAdapter(_space(), rel_tol=0.01, roots=2)
    values: dict[int, float] = {}

    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        values[sugg.trial_id] = float(sugg.values["K"])
        return _two_bounds(sugg)

    reporter = ConsoleProgressReporter(
        "bisection", adapter.counted_budget.worst, label=adapter.progress_label
    )
    session = _search(adapter, evaluate, reporter)

    descriptions = handles[0].descriptions
    assert descriptions[0] == "Calibrating (bisection) - bracketing K"
    assert all("best " not in text for text in descriptions)
    assert any("minimal root K in [" in text for text in descriptions)
    assert (
        descriptions[-1]
        == f"Calibrating (bisection) - root K = {values[session.best.trial_id]:.4g}"
    )


def test_a_one_root_search_shows_the_bracket_around_the_root(handles) -> None:
    adapter = BisectionAdapter(_space(), rel_tol=0.01)
    reporter = ConsoleProgressReporter(
        "bisection", adapter.counted_budget.worst, label=adapter.progress_label
    )

    _search(adapter, _one_bound, reporter)

    last = handles[0].descriptions[-1]
    assert last.startswith("Calibrating (bisection) - root K in [")
    low, high = (float(end) for end in last.split("[")[1].rstrip("]").split(", "))
    assert low <= ROOT_MAX * 1.001 and high >= ROOT_MAX * 0.999


def test_a_method_without_a_label_keeps_the_lowest_cost(handles) -> None:
    reporter = ConsoleProgressReporter("grid", 2)
    reporter.update(
        1, EvaluationResult(trial_id=1, sim_id=None, objective_value=0.5, status="completed")
    )
    reporter.update(
        2, EvaluationResult(trial_id=2, sim_id=None, objective_value=0.25, status="completed")
    )
    reporter.close()

    assert handles[0].descriptions[-1] == "Calibrating (grid) - best 0.25"
