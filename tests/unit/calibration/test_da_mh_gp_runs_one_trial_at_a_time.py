"""``da_mh_gp`` evaluates one trial at a time, and a parallel setting does not hang it.

The chain proposes its next point only once the previous one is told. With
``parallel > 1`` or ``batch_size > 1`` the engine asked for several points in
one batch, and the second ``next_point`` waited forever for a tell that comes
after the batch. The engine claimed ``supports_parallel``, so no check said so.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

pytest.importorskip("sklearn")

from hydromodpy.calibration.optim.engine import CalibrationEngine  # noqa: E402
from hydromodpy.calibration.optim.optimizer import (  # noqa: E402
    EvaluationResult,
    build_optimizer,
    engine_traits,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace  # noqa: E402

TIMEOUT_S = 60.0


def _space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="x", lower=-4.0, upper=4.0),
            CalibParameter(name="y", lower=-4.0, upper=4.0),
        ]
    )


def _evaluate(suggestion):
    x, y = float(suggestion.values["x"]), float(suggestion.values["y"])
    return EvaluationResult(
        trial_id=suggestion.trial_id,
        sim_id=None,
        objective_value=float(np.hypot(x - 1.0, y + 2.0)),
        status="completed",
    )


def _optimizer():
    return build_optimizer(
        "da_mh_gp",
        _space(),
        max_iter=12,
        n_init=4,
        burn_in=2,
        proposal_sigma=0.5,
        seed=3,
        sigma_noise=0.5,
    )


def test_the_engine_says_it_runs_one_trial_at_a_time() -> None:
    assert engine_traits("da_mh_gp").supports_parallel is False


@pytest.mark.parametrize("setting", [{"parallel": 3}, {"batch_size": 4}])
def test_a_parallel_setting_finishes(setting: dict[str, int]) -> None:
    optimizer = _optimizer()
    engine = CalibrationEngine(
        space=_space(), optimizer=optimizer, evaluator=_evaluate, max_iter=12, **setting
    )
    outcome: dict[str, object] = {}
    worker = threading.Thread(target=lambda: outcome.update(session=engine.run()), daemon=True)

    worker.start()
    worker.join(TIMEOUT_S)

    assert not worker.is_alive(), "the search waited for a point the chain cannot propose"
    assert outcome["session"].history
