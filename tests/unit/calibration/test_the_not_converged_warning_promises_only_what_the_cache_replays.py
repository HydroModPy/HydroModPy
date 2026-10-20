"""The "did NOT converge" warning names only what a re-run really replays.

The cache key holds the whole ``[calibration]`` table except its runtime keys.
``max_iter`` is one of those, so a larger budget replays the solved trials;
``tolerance``, ``seed``, ``method`` and ``method_options`` are in the key, so
changing one of them solves every trial again. The message used to promise a
replay after "loosening the tolerance".
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.cache import params_hash
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.runners.state import (
    build_cache_context,
    override_paths,
    space_from_config,
)

_DECLARED = {
    "method": "scipy_nelder_mead",
    "max_iter": 5,
    "tolerance": 0.01,
    "seed": 3,
    "method_options": {"maxiter": 50},
    "parameters": {"k": {"path": "flow.properties.k_aquifer", "bounds": [1e-6, 1e-2]}},
}


def _hash(**changes: object) -> str:
    cfg = CalibrationConfig.model_validate({**_DECLARED, **changes})
    context = build_cache_context(
        cfg=cfg,
        trial_ctx=None,
        space=space_from_config(cfg),
        override_paths=override_paths(cfg),
        objective_entrypoint=None,
    )
    return params_hash({"k": 1e-4}, context=context)


def _warning_of_a_search_that_ran_out(caplog) -> str:
    space = ParameterSpace(
        [
            CalibParameter(name="x", lower=-1.0, upper=1.0),
            CalibParameter(name="y", lower=-1.0, upper=1.0),
        ]
    )
    optimizer = build_optimizer("scipy_nelder_mead", space, seed=1, xatol=0.0, fatol=0.0)
    rng = np.random.default_rng(5)

    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=None,
            objective_value=float(rng.uniform(1.0, 2.0)),
            status="completed",
        )

    with caplog.at_level(logging.WARNING):
        CalibrationEngine(space=space, optimizer=optimizer, evaluator=evaluate, max_iter=12).run()
    (record,) = [r for r in caplog.records if "did NOT converge" in r.getMessage()]
    return record.getMessage()


def test_a_larger_budget_replays_and_the_warning_says_so(caplog) -> None:
    assert _hash(max_iter=500) == _hash()

    message = _warning_of_a_search_that_ran_out(caplog)
    assert "Raise max_iter" in message
    assert "replays the trials already solved" in message


@pytest.mark.parametrize(
    ("name", "change"),
    [
        ("tolerance", {"tolerance": 0.1}),
        ("seed", {"seed": 4}),
        ("method_options", {"method_options": {"maxiter": 60}}),
        ("method", {"method": "random_search", "tolerance": None, "method_options": {}}),
    ],
)
def test_what_the_warning_leaves_out_of_the_replay_is_in_the_key(name, change, caplog) -> None:
    assert _hash(**change) != _hash()

    message = _warning_of_a_search_that_ran_out(caplog)
    assert name in message
    # The sentence that names it says the key changes, not that a replay follows.
    sentence = next(s for s in message.split(".") if name in s)
    assert "cache key" in sentence
    assert "replays" not in sentence
