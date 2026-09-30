"""A search that still moves ``recharge.values`` would change nothing.

The soil reservoir computes the recharge MODFLOW reads; a calibration
parameter that reaches ``flow.sinks_sources.recharge.values``, whether by its
own name or by an explicit path, moves a rate no builder reads once a soil
section is declared.
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

_MESSAGE = (
    "moves flow.sinks_sources.recharge.values, which the soil reservoir "
    "replaces: the search would change nothing. Calibrate ru instead, with "
    "[calibration.parameters.ru] and its bounds in mm."
)


class _Project:
    def __init__(self, flow: FlowConfig) -> None:
        self.flow = flow


def _project_with_soil() -> _Project:
    soil = SoilReservoirConfig(ru=150.0)
    recharge = FlowRechargeConfig(soil=soil)
    sinks_sources = FlowSinksSourcesConfig(recharge=recharge)
    flow = FlowConfig.homogeneous(K=1e-4).model_copy(update={"sinks_sources": sinks_sources})
    return _Project(flow)


def _project_without_soil() -> _Project:
    recharge = FlowRechargeConfig()
    sinks_sources = FlowSinksSourcesConfig(recharge=recharge)
    flow = FlowConfig.homogeneous(K=1e-4).model_copy(update={"sinks_sources": sinks_sources})
    return _Project(flow)


def test_naming_the_quantity_recharge_values_is_refused() -> None:
    calibration = CalibrationConfig.model_validate({"parameters": {"recharge.values": {}}})

    with pytest.raises(ConfigError) as excinfo:
        resolve_parameter_targets(calibration, _project_with_soil())

    assert "[calibration.parameters.recharge.values]" in str(excinfo.value)
    assert _MESSAGE in str(excinfo.value)


def test_writing_the_path_to_recharge_values_is_refused() -> None:
    calibration = CalibrationConfig.model_validate(
        {"parameters": {"my_rate": {"path": "flow.sinks_sources.recharge.values"}}}
    )

    with pytest.raises(ConfigError) as excinfo:
        resolve_parameter_targets(calibration, _project_with_soil())

    assert "[calibration.parameters.my_rate]" in str(excinfo.value)
    assert _MESSAGE in str(excinfo.value)


def test_recharge_values_is_still_calibrable_without_a_soil_section() -> None:
    calibration = CalibrationConfig.model_validate({"parameters": {"recharge.values": {}}})

    resolve_parameter_targets(calibration, _project_without_soil())

    assert calibration.parameters["recharge.values"].path == "flow.sinks_sources.recharge.values"


def test_ru_is_still_calibrable_beside_a_soil_section() -> None:
    calibration = CalibrationConfig.model_validate({"parameters": {"ru": {"bounds": [30, 250]}}})

    resolve_parameter_targets(calibration, _project_with_soil())

    assert calibration.parameters["ru"].path == "flow.sinks_sources.recharge.soil.ru"
