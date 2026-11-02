"""A negative ``first_clim`` is a deficit under MODFLOW and a refusal under Boussinesq.

Its description promises the split into a recharge part and a deficit part. Only
MODFLOW 6 kept it. MODFLOW-NWT wrote a negative rate in RCH, and Boussinesq a
negative rate in its residual, past the refusal of negative values.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.forcing.common import ForcingCommonMixin
from hydromodpy.solver.boussinesq.forcing.recharge_resolution import RechargeResolutionMixin
from hydromodpy.solver.modflow_nwt.nwt.payloads.recharge_etp import (
    extract_negative_recharge_evt_payload,
)

pytestmark = pytest.mark.fast

STEADY_FIRST = np.array([True, False])


def test_modflow_nwt_routes_it_to_evt_on_the_steady_period_only() -> None:
    rch, evt = extract_negative_recharge_evt_payload(
        payload={0: 1.0, 1: 2.0}, nper=2, steady=STEADY_FIRST, first_clim=-0.5
    )

    assert rch == {0: 0.0, 1: 2.0}
    assert evt == {0: 0.5, 1: 0.0}


def test_modflow_nwt_routes_nothing_without_a_steady_period() -> None:
    payload = {0: 1.0, 1: 2.0}

    rch, evt = extract_negative_recharge_evt_payload(
        payload=payload, nper=2, steady=np.array([False, False]), first_clim=-0.5
    )

    assert rch is payload
    assert evt is None


class _Boussinesq(RechargeResolutionMixin, ForcingCommonMixin):
    def __init__(self, first_clim: object, *, first_period_steady: bool) -> None:
        self.flow = SimpleNamespace(
            flow_regime="transient",
            first_period_steady=first_period_steady,
            active_sinks_sources=["recharge"],
            sinks_sources={
                "recharge": SimpleNamespace(
                    first_clim=first_clim, values=[1.0, 2.0], heterogeneous_source=None
                )
            },
        )
        self.time_grid = None


def test_boussinesq_refuses_it_on_a_steady_period() -> None:
    with pytest.raises(ValueError, match="no EVT to route a deficit to"):
        _Boussinesq(-0.5, first_period_steady=True).resolve_recharge_series(2)


def test_boussinesq_keeps_the_rates_when_no_period_is_steady() -> None:
    series = _Boussinesq(-0.5, first_period_steady=False).resolve_recharge_series(2)

    assert series == (1.0, 2.0)
