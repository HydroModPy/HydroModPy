"""A calibration phase with regime = "soil": ru from the water budget, no solver.

The phase is refused before the first solve when it cannot hand ru to a later
phase. The budget itself is checked in ``tests/unit/model/forcing/test_soil_ru_budget.py``.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runners.phase_regime import regime_overrides
from hydromodpy.calibration.runners.staged_runner import _phase_plans
from hydromodpy.core.exceptions import ConfigValidationError

RU = {"bounds": [20.0, 1000.0], "path": "flow.sinks_sources.recharge.soil.ru"}
K = {"bounds": [1e-7, 1e-3], "search_space": "log", "path": "flow.param.K.field.value"}


def calibration(phases: list[dict]) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {"method": "scipy_nelder_mead", "parameters": {"ru": RU, "K": K}, "phases": phases}
    )


SOIL = {"name": "soil_capacity", "parameters": ["ru"], "regime": "soil"}
NEXT = {
    "name": "conductivity",
    "parameters": ["K"],
    "regime": "transient",
    "variable": "discharge",
    "objective": "nse",
}


def test_a_soil_phase_writes_nothing_into_the_model():
    cfg = calibration([SOIL, NEXT])
    assert regime_overrides(cfg.phases[0], {}) == {}


def test_a_soil_phase_before_a_search_is_planned():
    cfg = calibration([SOIL, NEXT])
    plans = _phase_plans(cfg, list(enumerate(cfg.phases)), {})
    assert [plan.decl.regime for plan in plans] == ["soil", "transient"]


@pytest.mark.parametrize(
    ("phases", "message"),
    [
        pytest.param([NEXT, SOIL], "none follows", id="soil phase last"),
        pytest.param(
            [{**SOIL, "parameters": ["ru", "K"]}, NEXT],
            "list the one parameter that moves ru",
            id="ru and K",
        ),
    ],
)
def test_a_soil_phase_that_cannot_hand_ru_on_is_refused(phases, message):
    cfg = calibration(phases)
    with pytest.raises(ConfigValidationError, match=message):
        _phase_plans(cfg, list(enumerate(cfg.phases)), {})
