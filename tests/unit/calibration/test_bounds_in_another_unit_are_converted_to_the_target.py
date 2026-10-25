"""Bounds written in another unit than the target reads are converted when the file loads.

Each sampled value is written as it is into the field, which reads it in its
own unit. A file that writes ``units = "m/s"`` on a conductivity the project
declares in ``m/day`` gets its bounds converted to ``m/day``, so the search
draws in the unit the model reads and the journal says so. A unit of another
dimension cannot be converted and is refused, naming both units. A factor of
``mode = "scale"`` has no unit, so writing one there is refused.
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import Field

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.parameters import ParameterSpace, apply_parameter_to_config
from hydromodpy.calibration.parameter_resolution import resolve_parameter_targets
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.exceptions import ConfigError

pytestmark = pytest.mark.unit

SECONDS_PER_DAY = 86_400.0


def _value_in(unit: str) -> type[HydroModelBase]:
    class _Value(HydroModelBase):
        value: Annotated[float | None, Profile.USER] = Field(
            default=None,
            json_schema_extra=field_metadata(
                calibrable=Calibrable(
                    search_space="log", units=unit, is_the_value_of_its_instance=True
                )
            ),
        )

    return _Value


def _project(unit: str, value: float) -> object:
    value_model = _value_in(unit)

    class _Parameter(HydroModelBase):
        field: Annotated[value_model, Profile.USER] = Field(default_factory=value_model)

    class _Flow(HydroModelBase):
        param: Annotated[dict[str, _Parameter], Profile.USER] = Field(default_factory=dict)

    class _Project:
        def __init__(self) -> None:
            self.flow = _Flow(param={"K": _Parameter(field=value_model(value=value))})

    return _Project()


def _resolved(project: object, **declaration: object) -> CalibrationConfig:
    calibration = CalibrationConfig.model_validate({"parameters": {"K": declaration}})
    resolve_parameter_targets(calibration, project)
    return calibration


def _space(calibration: CalibrationConfig) -> ParameterSpace:
    return ParameterSpace.from_toml_mapping(
        {name: decl.model_dump() for name, decl in calibration.parameters.items()}
    )


def test_bounds_in_m_per_s_on_a_conductivity_read_in_m_per_day_are_converted() -> None:
    calibration = _resolved(_project("m/day", 0.5), bounds=[1e-6, 1e-4], units="m/s")

    decl = calibration.parameters["K"]
    assert decl.units == "m/day"
    assert decl.bounds == pytest.approx([1e-6 * SECONDS_PER_DAY, 1e-4 * SECONDS_PER_DAY])


def test_the_sample_is_written_in_the_unit_the_model_reads() -> None:
    project = _project("m/day", 0.5)
    calibration = _resolved(project, bounds=[1e-6, 1e-4], units="m/s")
    param = _space(calibration)["K"]

    apply_parameter_to_config(project, param, param.lower)

    assert project.flow.param["K"].field.value == pytest.approx(1e-6 * SECONDS_PER_DAY)
    described = _space(calibration).describe_values({"K": param.lower})["K"]
    assert described["units"] == "m/day"


def test_bounds_in_m_per_day_on_a_conductivity_read_in_m_per_s_are_converted() -> None:
    calibration = _resolved(_project("m/s", 1e-5), bounds=[0.0864, 8.64], units="m/day")

    decl = calibration.parameters["K"]
    assert decl.units == "m/s"
    assert decl.bounds == pytest.approx([1e-6, 1e-4])


def test_converting_twice_changes_nothing() -> None:
    project = _project("m/day", 0.5)
    calibration = _resolved(project, bounds=[1e-6, 1e-4], units="m/s")

    resolve_parameter_targets(calibration, project)

    assert calibration.parameters["K"].bounds == pytest.approx([0.0864, 8.64])


def test_a_unit_of_another_dimension_is_refused_naming_both() -> None:
    with pytest.raises(ConfigError, match=r"'m'.*'m/day'"):
        _resolved(_project("m/day", 0.5), bounds=[1.0, 10.0], units="m")


def test_bounds_in_the_unit_the_target_reads_load_unchanged() -> None:
    calibration = _resolved(_project("m/day", 0.5), bounds=[0.01, 10.0], units="m/day")

    assert calibration.parameters["K"].bounds == [0.01, 10.0]


def test_bounds_without_a_unit_take_the_one_of_the_target() -> None:
    calibration = _resolved(_project("m/day", 0.5), bounds=[0.01, 10.0])

    assert calibration.parameters["K"].units == "m/day"


def test_a_unit_on_a_scale_factor_is_refused() -> None:
    with pytest.raises(ConfigError, match=r"scale.*factor"):
        _resolved(_project("m/day", 0.5), bounds=[0.5, 2.0], units="m/s", mode="scale")


def test_a_scale_factor_without_a_unit_loads() -> None:
    calibration = _resolved(_project("m/day", 0.5), bounds=[0.5, 2.0], mode="scale")

    assert calibration.parameters["K"].bounds == [0.5, 2.0]
