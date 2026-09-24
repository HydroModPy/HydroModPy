"""Both step_value callers share one refusal rule.

``SimulationTimeConfig`` (Pydantic validation at config load) and
``resolve_simulation_time_window`` (the launcher window helper) must reject
the same bad ``step_value``/``step_unit`` inputs with the same message, since
both delegate to ``reject_invalid_step_value_spec``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hydromodpy.core.time.window import (
    reject_invalid_step_value_spec,
    resolve_simulation_time_window,
)
from hydromodpy.simulation.planning.config import SimulationTimeConfig

_SHARED_REFUSALS = [
    (-5, None, "must be a positive integer"),
    (0, "day", "must be a positive integer"),
    (1, None, "has no unit"),
]


def _cfg_for_window(step_value: object, step_unit: object) -> SimpleNamespace:
    return SimpleNamespace(
        simulation=SimpleNamespace(
            time=SimpleNamespace(
                mode="explicit",
                start_datetime="2020-01-01 00:00:00",
                end_datetime="2020-01-02 00:00:00",
                step_value=step_value,
                step_unit=step_unit,
                coverage_policy="error",
            )
        )
    )


@pytest.mark.parametrize(("step_value", "step_unit", "match"), _SHARED_REFUSALS)
def test_planning_config_and_window_helper_refuse_the_same_inputs(
    step_value: object, step_unit: object, match: str
) -> None:
    with pytest.raises(ValidationError, match=match):
        SimulationTimeConfig(
            start_datetime="2020-01-01 00:00:00",
            end_datetime="2020-01-02 00:00:00",
            step_value=step_value,
            step_unit=step_unit,
        )

    with pytest.raises(ValueError, match=match):
        resolve_simulation_time_window(_cfg_for_window(step_value, step_unit))


def test_shared_rule_rejects_a_boolean_step_value_before_the_missing_unit_check() -> None:
    """Pydantic coerces a bare bool to int before validation, so this edge only
    reaches ``reject_invalid_step_value_spec`` untouched through the window
    helper's plain-object callers; exercise the shared function directly.
    """
    with pytest.raises(ValueError, match="must be a positive integer"):
        reject_invalid_step_value_spec(True, None)
