"""A zoned parameter is faced with the ceiling of the property it is a zone of.

The physical registry is consulted twice on the way in, and the two consultations
do not know the same thing. ``optim.parameters`` asks under the name the file gave
the parameter, which is all a bare name can do. The catalogue asks under the entry
the value belongs to, read off the config tree it walked.

They diverged exactly on a heterogeneous field: the catalogue names a zone
``Sy.zone_1`` and shows the specific-yield range beside it, while
``PHYSICAL_BOUNDS.get("sy.zone_1")`` is None, so the guard let a zone through at
0.9 and refused the same 0.9 on the homogeneous form. The resolution knows the
target, so it asks the question under the catalogue's own key.
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


class _Zones(HydroModelBase):
    """A field whose value is one number per zone, as a heterogeneous field is."""

    values: Annotated[dict[str, float], Profile.USER] = Field(
        default_factory=dict,
        json_schema_extra=field_metadata(
            calibrable=Calibrable(transform="log", is_the_value_of_its_instance=True)
        ),
    )


class _Parameter(HydroModelBase):
    field: Annotated[_Zones, Profile.USER] = Field(default_factory=_Zones)


class _Flow(HydroModelBase):
    param: Annotated[dict[str, _Parameter], Profile.USER] = Field(default_factory=dict)


class _Config:
    def __init__(self, flow: _Flow) -> None:
        self.flow = flow


def _project() -> _Config:
    return _Config(_Flow(param={"Sy": _Parameter(field=_Zones(values={"zone_1": 0.05}))}))


def _calibration(**parameters: dict) -> CalibrationConfig:
    return CalibrationConfig.model_validate({"parameters": parameters})


def test_the_zone_is_named_after_the_property_it_belongs_to() -> None:
    from hydromodpy.calibration.targets import calibration_targets

    (target,) = calibration_targets(_project())

    assert target.name == "Sy.zone_1"
    assert target.registry_id == "sy"
    assert target.physical_bounds == (1e-4, 0.5)


def test_a_zone_above_the_ceiling_is_refused() -> None:
    """0.9 is past the specific-yield ceiling, zoned or not."""
    calibration = _calibration(**{"Sy.zone_1": {"bounds": [1e-4, 0.9]}})

    with pytest.raises(ConfigError) as failure:
        resolve_parameter_targets(calibration, _project())

    assert "0.9" in str(failure.value)
    assert "specific yield" in str(failure.value)


def test_a_zone_inside_the_ceiling_is_accepted() -> None:
    calibration = _calibration(**{"Sy.zone_1": {"bounds": [1e-4, 0.3]}})

    resolve_parameter_targets(calibration, _project())

    assert calibration.parameters["Sy.zone_1"].path == "flow.param.Sy.field.values.zone_1"
