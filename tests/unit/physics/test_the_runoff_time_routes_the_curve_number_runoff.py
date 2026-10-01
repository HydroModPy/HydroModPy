"""``runoff_time`` routes the curve-number runoff without changing its volume.

``runoff_time = 0`` sends ``Q_cn`` to the outlet the same day it falls,
exactly as the unrouted term would. A longer time constant delays and
smooths the same pulse through the exact linear-reservoir solution already
used for the transit store (the discrete peak lands on the day after the
pulse once ``k`` is not tiny, exactly as it does for the transit store), and
the routed total plus what the reservoir still holds matches the raw total.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilParameters,
    full_soil,
    run_soil_balance,
)

_CN = 85.0
_RU = 150.0


def _params(runoff_time_days: float) -> SoilParameters:
    return SoilParameters(
        ru_mm=np.array([_RU]),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
        curve_number=_CN,
        runoff_time_days=runoff_time_days,
    )


def _one_wet_day_forcing(n_days: int) -> tuple[np.ndarray, np.ndarray]:
    precipitation = np.zeros((n_days, 1))
    precipitation[0, 0] = 40.0
    etp = np.zeros((n_days, 1))
    return precipitation, etp


def test_runoff_time_zero_sends_the_runoff_the_same_day() -> None:
    precipitation, etp = _one_wet_day_forcing(5)
    params = _params(0.0)

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))

    assert fluxes.runoff_cn[0, 0] > 0.0
    assert np.all(fluxes.runoff_cn[1:, 0] == 0.0)


def test_a_longer_runoff_time_delays_and_smooths_the_same_pulse() -> None:
    n_days = 60
    precipitation, etp = _one_wet_day_forcing(n_days)

    immediate = run_soil_balance(precipitation, etp, _params(0.0), full_soil(_params(0.0)))
    routed = run_soil_balance(precipitation, etp, _params(5.0), full_soil(_params(5.0)))

    assert routed.runoff_cn[0, 0] < immediate.runoff_cn[0, 0]
    assert np.any(routed.runoff_cn[1:, 0] > 0.0)

    peak = int(np.argmax(routed.runoff_cn[:, 0]))
    assert peak in (0, 1)
    assert np.all(np.diff(routed.runoff_cn[peak:, 0]) <= 0.0)

    remaining = float(routed.end.cn_storage_mm[0])
    assert routed.runoff_cn[:, 0].sum() + remaining == pytest.approx(
        immediate.runoff_cn[:, 0].sum(), abs=1e-9
    )


def test_a_wider_time_constant_spreads_the_pulse_further() -> None:
    n_days = 90
    precipitation, etp = _one_wet_day_forcing(n_days)

    short = run_soil_balance(precipitation, etp, _params(2.0), full_soil(_params(2.0)))
    long = run_soil_balance(precipitation, etp, _params(8.0), full_soil(_params(8.0)))

    assert long.runoff_cn[0, 0] < short.runoff_cn[0, 0]

    short_remaining = float(short.end.cn_storage_mm[0])
    long_remaining = float(long.end.cn_storage_mm[0])
    assert long.runoff_cn[:, 0].sum() + long_remaining == pytest.approx(
        short.runoff_cn[:, 0].sum() + short_remaining, abs=1e-9
    )
