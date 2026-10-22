"""Bounds written in another unit than the target reads are refused, with the conversion.

Each sampled value is written as it is into the field, which reads it in its
own unit. A file that wrote ``units = "m/s"`` on a conductivity the project
declares in ``m/day`` used to load, and every candidate landed 86 400 times
too low. The file is refused when it loads, and the message gives the bounds
converted into the unit the target reads.
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import Field

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.parameter_resolution import resolve_parameter_targets
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.exceptions import ConfigError

pytestmark = pytest.mark.unit


class _Value(HydroModelBase):
    value: Annotated[float | None, Profile.USER] = Field(
        default=None,
        json_schema_extra=field_metadata(
            calibrable=Calibrable(
                search_space="log", units="m/day", is_the_value_of_its_instance=True
            )
        ),
    )


class _Parameter(HydroModelBase):
    field: Annotated[_Value, Profile.USER] = Field(default_factory=_Value)


class _Flow(HydroModelBase):
    param: Annotated[dict[str, _Parameter], Profile.USER] = Field(default_factory=dict)


class _Project:
    def __init__(self) -> None:
        self.flow = _Flow(param={"K": _Parameter(field=_Value(value=0.5))})


def _resolved(**declaration: object) -> CalibrationConfig:
    calibration = CalibrationConfig.model_validate({"parameters": {"K": declaration}})
    resolve_parameter_targets(calibration, _Project())
    return calibration


def test_bounds_in_another_unit_are_refused_with_the_conversion() -> None:
    with pytest.raises(ConfigError, match=r"bounds = \[0\.0864, 8\.64\]"):
        _resolved(bounds=[1e-6, 1e-4], units="m/s")


def test_bounds_in_the_unit_the_target_reads_load() -> None:
    calibration = _resolved(bounds=[0.01, 10.0], units="m/day")

    assert calibration.parameters["K"].units == "m/day"


def test_bounds_without_a_unit_take_the_one_of_the_target() -> None:
    calibration = _resolved(bounds=[0.01, 10.0])

    assert calibration.parameters["K"].units == "m/day"


def test_a_scale_factor_carries_no_unit_to_compare() -> None:
    calibration = _resolved(bounds=[0.5, 2.0], units="m/s", mode="scale")

    assert calibration.parameters["K"].mode == "scale"
