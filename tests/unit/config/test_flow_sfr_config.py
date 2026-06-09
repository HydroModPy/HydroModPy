"""The FlowReachNetworkConfig physics payload for the MODFLOW 6 SFR package.

An SFR network rides inside ``[flow.sinks_sources.sfr.<id>]``. It carries the
delineation thresholds, the streambed hydraulics, the reach-width law and the
transient forcings, plus the optional MVR coupling to a lake. The tests check:

* a well-formed delineated network validates, with the width discriminated union
  picking the right class from ``kind``;
* an explicit-reach network validates with no threshold required;
* a bad config is rejected: both thresholds set, neither threshold set (when
  delineating), an unknown ``streambed_k_unit``, an out-of-range FACTOR coupling,
  an extra field (``extra='forbid'``);
* the network rides on the container under ``sfr`` and the SFR boundary id is
  registered;
* the LAK outlet mover now accepts a ``reach`` receiver and enforces lake XOR reach.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.physics.flow.boundary_condition_registry import SUPPORTED_FLOW_BOUNDARY_IDS
from hydromodpy.physics.flow.sinks_sources import (
    FlowLakeOutletMover,
    FlowReachNetworkConfig,
    FlowReachWidthByOrder,
    FlowReachWidthConstant,
    FlowReachWidthPowerLaw,
    FlowSinksSourcesConfig,
)


def test_sfr_config_validates_delineated_network_and_width_union() -> None:
    net = FlowReachNetworkConfig.model_validate(
        {
            "stream_threshold_km2": 1.5,
            "manning": 0.04,
            "streambed_k": 1e-5,
            "streambed_k_unit": "m/day",
            "streambed_thickness": "0.5 m",
            "width": {"kind": "by_order", "widths": {1: "1 m", 2: "3 m"}},
            "outflow_to_lake": 1,
        }
    )
    assert net.stream_threshold_km2 == pytest.approx(1.5)
    assert net.stream_threshold_cells is None
    assert isinstance(net.width, FlowReachWidthByOrder)
    assert net.outflow_to_lake == 1
    assert net.outflow_mvrtype == "FACTOR"

    constant = FlowReachNetworkConfig.model_validate(
        {"stream_threshold_cells": 200, "width": {"kind": "constant", "value": "2 m"}}
    )
    assert isinstance(constant.width, FlowReachWidthConstant)

    power = FlowReachNetworkConfig.model_validate(
        {"stream_threshold_cells": 200, "width": {"kind": "power_law", "coef": 1.2, "exp": 0.5}}
    )
    assert isinstance(power.width, FlowReachWidthPowerLaw)


def test_sfr_config_default_width_is_a_constant_metre() -> None:
    net = FlowReachNetworkConfig.model_validate({"stream_threshold_cells": 100})
    assert isinstance(net.width, FlowReachWidthConstant)
    assert net.connected_to_aquifer is True


def test_sfr_config_explicit_reaches_need_no_threshold() -> None:
    net = FlowReachNetworkConfig.model_validate(
        {
            "reaches": [
                {
                    "cell": {"kind": "cell", "cell": [0, 0, 5]},
                    "length": "100 m",
                    "width": "2 m",
                    "slope": 1e-3,
                    "top": "50 m",
                    "downstream": [2],
                },
                {"length": "100 m", "width": "2 m", "slope": 1e-3, "top": "49 m", "upstream": [1]},
            ]
        }
    )
    assert net.reaches is not None
    assert len(net.reaches) == 2
    assert net.reaches[0].downstream == [2]


def test_sfr_config_rejects_bad_thresholds_and_units() -> None:
    with pytest.raises(ValidationError, match="exactly one of stream_threshold"):
        FlowReachNetworkConfig.model_validate(
            {"stream_threshold_km2": 1.0, "stream_threshold_cells": 100}
        )
    with pytest.raises(ValidationError, match="exactly one of stream_threshold"):
        FlowReachNetworkConfig.model_validate({"manning": 0.03})
    with pytest.raises(ValidationError):
        FlowReachNetworkConfig.model_validate(
            {"stream_threshold_cells": 100, "streambed_k_unit": "kg"}
        )
    with pytest.raises(ValidationError, match="FACTOR"):
        FlowReachNetworkConfig.model_validate(
            {"stream_threshold_cells": 100, "outflow_to_lake": 1, "outflow_value": 2.0}
        )
    with pytest.raises(ValidationError):
        FlowReachNetworkConfig.model_validate({"stream_threshold_cells": 100, "bogus": 1})


def test_sfr_rides_on_the_container_and_is_registered() -> None:
    container = FlowSinksSourcesConfig.model_validate(
        {"sfr": {"main": {"stream_threshold_cells": 150}}}
    )
    assert "main" in container.sfr
    assert container.sfr["main"].stream_threshold_cells == 150
    assert "sfr" in SUPPORTED_FLOW_BOUNDARY_IDS


def test_lake_outlet_mover_accepts_reach_receiver_and_enforces_xor() -> None:
    to_lake = FlowLakeOutletMover.model_validate({"lake": 2})
    assert to_lake.lake == 2 and to_lake.reach is None

    to_reach = FlowLakeOutletMover.model_validate({"reach": 3, "mvrtype": "UPTO", "value": 0.4})
    assert to_reach.reach == 3 and to_reach.lake is None

    with pytest.raises(ValidationError, match="exactly one of lake or reach"):
        FlowLakeOutletMover.model_validate({"lake": 1, "reach": 2})
    with pytest.raises(ValidationError, match="exactly one of lake or reach"):
        FlowLakeOutletMover.model_validate({})
