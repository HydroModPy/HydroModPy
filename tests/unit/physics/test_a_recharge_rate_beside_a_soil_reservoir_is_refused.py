"""A recharge rate written beside a soil reservoir would be silently ignored.

``[flow.sinks_sources.recharge.soil]`` computes the recharge itself, so a
``values`` written in the same section names a rate MODFLOW never sees.
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig


def test_a_recharge_rate_beside_a_soil_reservoir_is_refused() -> None:
    text = (
        "flow.sinks_sources.recharge.values = 2.0 is ignored when "
        "[flow.sinks_sources.recharge.soil] computes the recharge: remove values, "
        "or remove the soil section to impose this rate."
    )
    with pytest.raises(ValidationError, match=re.escape(text)):
        FlowRechargeConfig(values=2.0, soil=SoilReservoirConfig(ru=100.0))


def test_a_recharge_rate_built_by_code_without_soil_passes() -> None:
    recharge = FlowRechargeConfig(values=0.0)

    assert recharge.soil is None
    assert recharge.values == 0.0
