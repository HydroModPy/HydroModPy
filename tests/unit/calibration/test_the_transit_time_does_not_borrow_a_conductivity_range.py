"""A soil leaf named like a hydraulic property does not borrow its range.

``PHYSICAL_BOUNDS`` already knows ``"t"`` (transmissivity), and a bare leaf
lookup would have handed ``soil.transit_time`` that range instead of the one a
soil delay actually respects. ``_REGISTRY_ID_BY_PATH`` binds each soil path to
its own ``soil_*`` key, never found by the bare leaf name.
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


def test_transit_time_reads_its_own_range_not_a_transmissivity() -> None:
    by_name = targets_by_name(calibration_targets(_project()))

    transit_time = by_name["soil.transit_time"]

    assert transit_time.registry_id == "soil_transit_time"
    assert transit_time.physical_bounds == (0.0, 30.0)


def test_alpha_never_answers_to_its_bare_leaf_name() -> None:
    by_name = targets_by_name(calibration_targets(_project()))

    alpha = by_name["soil.alpha"]

    assert alpha.registry_id == "soil_alpha"
    assert alpha.registry_id != "alpha"
