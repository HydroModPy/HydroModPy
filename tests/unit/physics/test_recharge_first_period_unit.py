"""The first-period recharge override must be read in the unit it was written in.

``[flow.sinks_sources.recharge]`` declares one ``units`` for its payload, and the
flow runtime converts ``values`` to m/s on the way in. ``first_clim`` accepts the
same three shapes as a payload entry, including a bare number, and that number
was carried through untouched: a model written in ``mm/day`` and overriding its
first period with ``2`` started on 2 m/s, eight orders of magnitude out, with
nothing said.
"""

from __future__ import annotations

import pytest

from hydromodpy.physics.flow.flow import Flow
from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig

_MM_PER_DAY_IN_M_PER_S = 1e-3 / 86400.0


def _normalized(recharge: FlowRechargeConfig) -> FlowRechargeConfig:
    return Flow._normalize_recharge_config(recharge, location_prefix="flow.sinks_sources.recharge")


def test_a_numeric_first_period_follows_the_payload_unit() -> None:
    normalized = _normalized(FlowRechargeConfig(values=[1.0, 2.0], first_clim=2.0, units="mm/day"))

    assert normalized.units == "m/s"
    assert normalized.first_clim == pytest.approx(2.0 * _MM_PER_DAY_IN_M_PER_S)


def test_a_keyword_first_period_is_left_alone() -> None:
    normalized = _normalized(
        FlowRechargeConfig(values=[1.0, 2.0], first_clim="mean", units="mm/day")
    )

    assert normalized.first_clim == "mean"


def test_a_payload_already_in_si_is_unchanged() -> None:
    normalized = _normalized(
        FlowRechargeConfig(values=[1e-8, 2e-8], first_clim=1.5e-8, units="m/s")
    )

    assert normalized.first_clim == pytest.approx(1.5e-8)
