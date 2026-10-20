"""A cost cached under another scoring rule is not served again.

The session now reads its window as the run does (decision m01): a pair
counts when its whole period lies in the window, not when its end stamp does.
The same parameters therefore score on other periods than before, and a cost
cached under the old reading must not be replayed. The cache key carries the
version of the scoring rule, so the next bump of the rule re-solves too.
"""

from __future__ import annotations

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.cache import params_hash
from hydromodpy.calibration.runners import state
from hydromodpy.results.metric_rule import METRIC_RULE_VERSION

_DECLARED = {
    "method": "scipy_nelder_mead",
    "max_iter": 5,
    "parameters": {"k": {"path": "flow.properties.k_aquifer", "bounds": [1e-6, 1e-2]}},
}


def _context() -> dict[str, object]:
    cfg = CalibrationConfig.model_validate(_DECLARED)
    return state.build_cache_context(
        cfg=cfg,
        trial_ctx=None,
        space=state.space_from_config(cfg),
        override_paths=state.override_paths(cfg),
        objective_entrypoint=None,
    )


def test_the_context_names_the_rule_the_cost_was_scored_under() -> None:
    assert _context()["metric_rule_version"] == METRIC_RULE_VERSION


def test_a_cost_hashed_before_the_rule_was_keyed_is_not_found() -> None:
    context = _context()
    before = {key: value for key, value in context.items() if key != "metric_rule_version"}

    assert params_hash({"k": 1e-4}, context=context) != params_hash({"k": 1e-4}, context=before)


def test_another_rule_version_gives_another_key(monkeypatch) -> None:
    now = params_hash({"k": 1e-4}, context=_context())
    monkeypatch.setattr(state, "METRIC_RULE_VERSION", f"{METRIC_RULE_VERSION}-next")

    assert params_hash({"k": 1e-4}, context=_context()) != now
