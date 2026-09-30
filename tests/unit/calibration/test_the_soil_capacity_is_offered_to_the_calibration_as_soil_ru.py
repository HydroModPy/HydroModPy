"""The soil reservoir offers five named targets to a calibration.

Each carries the unit its own field declares, not the ``mm/day`` its
``FlowRechargeConfig`` parent declares for the recharge rate it replaces.
``impervious_fraction`` is a switch on the geometry, not a value to search
between two bounds, and declares no ``Calibrable``.
"""

from __future__ import annotations

from hydromodpy.calibration.targets import calibration_targets, targets_by_name
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


def test_the_soil_reservoir_offers_five_named_targets_with_their_own_units() -> None:
    by_name = targets_by_name(calibration_targets(_project()))

    assert by_name["soil.ru"].units == "mm"
    assert by_name["soil.alpha"].units == "-"
    assert by_name["soil.kc"].units == "-"
    assert by_name["soil.bypass_fraction"].units == "-"
    assert by_name["soil.transit_time"].units == "day"


def test_impervious_fraction_is_not_offered() -> None:
    by_name = targets_by_name(calibration_targets(_project()))

    assert "soil.impervious_fraction" not in by_name
