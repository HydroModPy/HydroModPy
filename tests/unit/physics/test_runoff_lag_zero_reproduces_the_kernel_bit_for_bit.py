"""``runoff_lag = 0`` is bit-identical to the kernel before this feature.

Mirrors ``test_curve_number_off_reproduces_the_kernel_bit_for_bit.py``: the
lag must cost nothing when it is zero, whether the field is left at its
default or set to 0.0 explicitly, with the curve-number routing active so the
series it would delay is not itself empty.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilParameters,
    full_soil,
    run_soil_balance,
)

_PARAMETER_SETS = (
    (0.6, 1.0, 0.0, 0.0, 0.0, 75.0, 0.0),
    (0.5, 1.2, 0.2, 0.1, 5.0, 85.0, 2.0),
    (1.0, 0.0, 0.3, 0.0, 30.0, 90.0, 3.5),
)


def _synthetic_forcing() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(3)
    n_days, n_columns = 500, 12
    wet = rng.random((n_days, n_columns)) < 0.4
    precipitation = np.where(wet, rng.gamma(0.8, 6.0, (n_days, n_columns)), 0.0)
    etp = rng.uniform(0.0, 5.0, (n_days, n_columns))
    ru_mm = rng.uniform(20.0, 300.0, n_columns)
    return precipitation, etp, ru_mm


def test_runoff_lag_left_at_its_default_matches_setting_it_to_zero() -> None:
    precipitation, etp, ru_mm = _synthetic_forcing()

    for (
        alpha,
        kc,
        impervious_fraction,
        bypass_fraction,
        transit_time_days,
        curve_number,
        runoff_time_days,
    ) in _PARAMETER_SETS:
        params_default = SoilParameters(
            ru_mm=ru_mm,
            alpha=alpha,
            kc=kc,
            impervious_fraction=impervious_fraction,
            bypass_fraction=bypass_fraction,
            transit_time_days=transit_time_days,
            curve_number=curve_number,
            runoff_time_days=runoff_time_days,
        )
        params_explicit_zero = SoilParameters(
            ru_mm=ru_mm,
            alpha=alpha,
            kc=kc,
            impervious_fraction=impervious_fraction,
            bypass_fraction=bypass_fraction,
            transit_time_days=transit_time_days,
            curve_number=curve_number,
            runoff_time_days=runoff_time_days,
            runoff_lag_days=0.0,
        )

        before = run_soil_balance(precipitation, etp, params_default, full_soil(params_default))
        after = run_soil_balance(
            precipitation, etp, params_explicit_zero, full_soil(params_explicit_zero)
        )

        assert np.array_equal(before.etr, after.etr)
        assert np.array_equal(before.recharge, after.recharge)
        assert np.array_equal(before.runoff, after.runoff)
        assert np.array_equal(before.runoff_cn, after.runoff_cn)
        assert np.array_equal(before.cn_storage, after.cn_storage)
        assert np.all(after.lag_storage == 0.0)
        assert np.all(after.lag_storage_start == 0.0)
