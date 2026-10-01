"""``[calibration.parameters.curve_number]`` and ``.runoff_time`` resolve by name.

Mirrors ``test_the_impervious_fraction_is_calibrable.py``: the file names the
quantity, the catalogue resolves it under ``flow.sinks_sources.recharge.soil``,
and a bound the physical registry rules out is caught at load.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.parameter_resolution import resolve_parameter_targets
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.flow.sinks_sources.container import FlowSinksSourcesConfig
from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig


class _Project:
    def __init__(self, flow: FlowConfig) -> None:
        self.flow = flow


def _project() -> _Project:
    soil = SoilReservoirConfig(ru=150.0, curve_number=80.0)
    recharge = FlowRechargeConfig(soil=soil)
    sinks_sources = FlowSinksSourcesConfig(recharge=recharge)
    flow = FlowConfig.homogeneous(K=1e-4).model_copy(update={"sinks_sources": sinks_sources})
    return _Project(flow)


def test_curve_number_resolves_to_the_soil_field_in_dimensionless_units() -> None:
    calibration = CalibrationConfig.model_validate(
        {"parameters": {"curve_number": {"bounds": [55.0, 90.0]}}}
    )

    resolve_parameter_targets(calibration, _project())

    decl = calibration.parameters["curve_number"]
    assert decl.path == "flow.sinks_sources.recharge.soil.curve_number"
    assert decl.units == "-"


def test_runoff_time_resolves_to_the_soil_field_in_days() -> None:
    calibration = CalibrationConfig.model_validate(
        {"parameters": {"runoff_time": {"bounds": [0.0, 5.0]}}}
    )

    resolve_parameter_targets(calibration, _project())

    decl = calibration.parameters["runoff_time"]
    assert decl.path == "flow.sinks_sources.recharge.soil.runoff_time"
    assert decl.units == "day"


def test_a_curve_number_bound_past_the_registry_is_refused_at_load() -> None:
    calibration = CalibrationConfig.model_validate(
        {"parameters": {"curve_number": {"bounds": [10.0, 90.0]}}}
    )

    with pytest.raises(ConfigError, match="curve_number"):
        resolve_parameter_targets(calibration, _project())


def test_a_runoff_time_bound_past_the_registry_is_refused_at_load() -> None:
    calibration = CalibrationConfig.model_validate(
        {"parameters": {"runoff_time": {"bounds": [0.0, 20.0]}}}
    )

    with pytest.raises(ConfigError, match="runoff_time"):
        resolve_parameter_targets(calibration, _project())
