"""Two trials at the same objective: the kept run and its replay name the same one.

The smaller trial number wins a tie, and a parallel batch is numbered in the
order the optimizer made it, before any worker starts. A second session on
the same search then gives each candidate the same number, so the run kept
by one session and the run a replay writes are the same trial.
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.persistence import CalibrationPersistence, PhaseContext
from hydromodpy.calibration.runners.promotion import select_trials_to_promote

pytestmark = pytest.mark.unit

PHASE = PhaseContext("k_grid", 0, 0)


def _open(tmp_path: Path) -> CalibrationPersistence:
    session_dir = tmp_path / "sessions" / "tie"
    session_dir.mkdir(parents=True)
    persistence = CalibrationPersistence(session_dir)
    persistence.start_session(
        session_id="a" * 32,
        case_id="tie",
        site="nancon",
        project="demo",
        config_hash="c" * 64,
        hydromodpy_version="2.0.0a5",
        method="grid",
        objective_name="nse",
        search_space={"K": {"bounds": [1e-5, 1e-4]}},
        objective_window=None,
    )
    return persistence


def _record(persistence: CalibrationPersistence, engine_id: int, k: float, cost: float) -> int:
    line = persistence.append_iteration(
        ParamSuggestion(trial_id=engine_id, values={"K": k}),
        EvaluationResult(trial_id=engine_id, sim_id=None, objective_value=cost, status="completed"),
        phase=PHASE,
    )
    return line.trial


class _OneBatch:
    """Serve one batch of suggestions, then converge."""

    name = "one_batch"

    def __init__(self, values: list[float]) -> None:
        self._values = list(values)
        self._told: list[EvaluationResult] = []

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        batch = [
            ParamSuggestion(trial_id=index, values={"K": value})
            for index, value in enumerate(self._values[:n])
        ]
        self._values = self._values[n:]
        return batch

    def tell(self, results: list[EvaluationResult]) -> None:
        self._told.extend(results)

    def best(self) -> EvaluationResult | None:
        return min(self._told, key=lambda r: r.objective_value) if self._told else None

    def converged(self) -> bool:
        return bool(self._told)


def test_a_tie_goes_to_the_smaller_trial_number_whatever_the_journal_order(
    tmp_path: Path,
) -> None:
    persistence = _open(tmp_path)
    persistence.assign_trial_numbers([0, 1], PHASE)
    _record(persistence, 1, 1e-4, 0.3)
    _record(persistence, 0, 1e-5, 0.3)

    best = persistence.best_trial("k_grid")
    assert best is not None
    assert best.trial == 1
    assert [row["iteration"] for row in persistence.top_n(2, "k_grid")] == [1, 2]
    promoted = select_trials_to_promote(SimpleNamespace(save_runs="all"), persistence, "k_grid")
    assert [row["iteration"] for row in promoted] == [1, 2]


def test_a_parallel_batch_is_numbered_in_the_order_the_optimizer_made_it(
    tmp_path: Path,
) -> None:
    """The second candidate starts first; it still takes the second number."""
    persistence = _open(tmp_path)
    first_may_start = threading.Event()
    numbers: dict[float, int] = {}
    lock = threading.Lock()

    def _evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        if sugg.trial_id == 0:
            assert first_may_start.wait(timeout=5.0)
        number = persistence.assign_trial_number(sugg.trial_id, PHASE)
        with lock:
            numbers[sugg.values["K"]] = number
        if sugg.trial_id == 1:
            first_may_start.set()
        return EvaluationResult(
            trial_id=sugg.trial_id, sim_id=None, objective_value=0.3, status="completed"
        )

    engine = CalibrationEngine(
        space=ParameterSpace([CalibParameter(name="K", lower=1e-5, upper=1e-4)]),
        optimizer=_OneBatch([1e-5, 1e-4]),
        evaluator=_evaluator,
        before_batch=lambda batch: persistence.assign_trial_numbers(
            [sugg.trial_id for sugg in batch], PHASE
        ),
        max_trials=2,
        batch_size=2,
        parallel=2,
    )
    engine.run()

    assert numbers == {1e-5: 1, 1e-4: 2}
