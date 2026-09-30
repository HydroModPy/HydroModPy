"""A calibrated ru cannot search past a soil water capacity's physical ceiling.

``[calibration.parameters.ru]`` is resolved to ``soil.ru``, and its bounds are
faced with the ``soil_ru`` entry of the physical registry, not with a generic
``ru`` the registry does not know.
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
    soil = SoilReservoirConfig(ru=150.0)
    recharge = FlowRechargeConfig(soil=soil)
    sinks_sources = FlowSinksSourcesConfig(recharge=recharge)
    flow = FlowConfig.homogeneous(K=1e-4).model_copy(update={"sinks_sources": sinks_sources})
    return _Project(flow)


def test_a_bound_beyond_the_registry_is_refused_at_load() -> None:
    calibration = CalibrationConfig.model_validate({"parameters": {"ru": {"bounds": [30, 2000]}}})

    with pytest.raises(ConfigError):
        resolve_parameter_targets(calibration, _project())


def test_a_bound_inside_the_registry_is_accepted() -> None:
    calibration = CalibrationConfig.model_validate({"parameters": {"ru": {"bounds": [30, 250]}}})

    resolve_parameter_targets(calibration, _project())

    assert calibration.parameters["ru"].path == "flow.sinks_sources.recharge.soil.ru"
