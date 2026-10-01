"""``[calibration.parameters.impervious_fraction]`` resolves and is bounds-checked.

Mirrors ``test_the_evt_extinction_depth_is_calibrable.py``: the file names the
quantity, the catalogue resolves it to
``flow.sinks_sources.recharge.soil.impervious_fraction``, and a bound the
physical registry rules out (1 or more, which the field validator also
refuses) is caught at load, before any trial runs.
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


def test_the_short_name_resolves_to_the_soil_field() -> None:
    calibration = CalibrationConfig.model_validate(
        {"parameters": {"impervious_fraction": {"bounds": [0.0, 0.08]}}}
    )

    resolve_parameter_targets(calibration, _project())

    decl = calibration.parameters["impervious_fraction"]
    assert decl.path == "flow.sinks_sources.recharge.soil.impervious_fraction"
    assert decl.units == "-"
    assert decl.bounds == [0.0, 0.08]


def test_a_bound_at_or_past_one_is_refused_at_load() -> None:
    calibration = CalibrationConfig.model_validate(
        {"parameters": {"impervious_fraction": {"bounds": [0.0, 1.0]}}}
    )

    with pytest.raises(ConfigError, match="impervious_fraction"):
        resolve_parameter_targets(calibration, _project())


def test_a_bound_inside_the_registry_is_accepted() -> None:
    calibration = CalibrationConfig.model_validate(
        {"parameters": {"impervious_fraction": {"bounds": [0.0, 0.3]}}}
    )

    resolve_parameter_targets(calibration, _project())

    assert calibration.parameters["impervious_fraction"].bounds == [0.0, 0.3]
