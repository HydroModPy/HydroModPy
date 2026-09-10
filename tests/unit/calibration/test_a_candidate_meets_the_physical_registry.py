"""A candidate the search writes has to face the same ceiling a literal does.

The declared bounds are checked at load time, which refuses the impossible
region once. That is not enough for ``mode = "scale"``: there the candidate is a
multiplier, so the value that reaches the configuration is the base times the
sample, and legal bounds on the multiplier say nothing about where the product
lands. A scale of 8 on a specific yield of 0.1 writes 0.8, past the physical
ceiling of 0.5, and only the solver would notice.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.optim.parameters import (
    CalibParameter,
    apply_parameter_to_config,
)


class _Field:
    def __init__(self, value: float) -> None:
        self.value = value


class _Param:
    def __init__(self, value: float) -> None:
        self.field = _Field(value)


class _Flow:
    def __init__(self, value: float) -> None:
        self.param = {"Sy": _Param(value)}


class _Cfg:
    def __init__(self, value: float = 0.1) -> None:
        self.flow = _Flow(value)


def _parameter(mode: str, name: str = "Sy") -> CalibParameter:
    return CalibParameter(
        name=name,
        lower=0.5,
        upper=8.0,
        path=f"flow.param.{name}.field.value",
        mode=mode,
        units="-",
    )


def test_a_scale_that_lands_past_the_ceiling_is_refused() -> None:
    cfg = _Cfg(0.1)

    with pytest.raises(ValueError, match="Sy"):
        apply_parameter_to_config(cfg, _parameter("scale"), 8.0)


def test_the_refusal_names_the_value_that_would_have_been_written() -> None:
    with pytest.raises(ValueError) as caught:
        apply_parameter_to_config(_Cfg(0.1), _parameter("scale"), 8.0)

    assert "0.8" in str(caught.value)


def test_a_scale_that_stays_inside_is_written() -> None:
    cfg = _Cfg(0.1)

    apply_parameter_to_config(cfg, _parameter("scale"), 4.0)

    assert cfg.flow.param["Sy"].field.value == pytest.approx(0.4)


def test_a_replaced_value_is_checked_too() -> None:
    param = CalibParameter(
        name="Sy", lower=1e-4, upper=0.9, path="flow.param.Sy.field.value", units="-"
    )

    with pytest.raises(ValueError, match="Sy"):
        apply_parameter_to_config(_Cfg(0.1), param, 0.9)


def test_an_id_the_registry_does_not_know_is_left_alone() -> None:
    cfg = _Cfg(0.1)
    param = CalibParameter(
        name="weird", lower=0.0, upper=100.0, path="flow.param.Sy.field.value", units="-"
    )

    apply_parameter_to_config(cfg, param, 99.0)

    assert cfg.flow.param["Sy"].field.value == pytest.approx(99.0)
