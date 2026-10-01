"""``curve_number = None`` is bit-identical to the kernel before this feature.

The curve-number term and its routing reservoir must cost nothing when the
field is off: ``q_cn`` is exactly zero every day, so every other quantity
follows the same float64 operations as before, down to the bit.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilParameters,
    full_soil,
    run_soil_balance,
)

_PARAMETER_SETS = (
    (0.6, 1.0, 0.0, 0.0, 0.0),
    (0.5, 1.2, 0.2, 0.1, 5.0),
    (1.0, 0.0, 0.3, 0.0, 30.0),
)


def _synthetic_forcing() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(1)
    n_days, n_columns = 1000, 20
    wet = rng.random((n_days, n_columns)) < 0.4
    precipitation = np.where(wet, rng.gamma(0.8, 6.0, (n_days, n_columns)), 0.0)
    etp = rng.uniform(0.0, 5.0, (n_days, n_columns))
    ru_mm = rng.uniform(0.0, 300.0, n_columns)
    ru_mm[:2] = 0.0
    return precipitation, etp, ru_mm


def test_curve_number_none_is_bit_identical_to_the_kernel_without_it() -> None:
    precipitation, etp, ru_mm = _synthetic_forcing()

    for alpha, kc, impervious_fraction, bypass_fraction, transit_time_days in _PARAMETER_SETS:
        params_without_field = SoilParameters(
            ru_mm=ru_mm,
            alpha=alpha,
            kc=kc,
            impervious_fraction=impervious_fraction,
            bypass_fraction=bypass_fraction,
            transit_time_days=transit_time_days,
        )
        params_with_default_runoff_time = SoilParameters(
            ru_mm=ru_mm,
            alpha=alpha,
            kc=kc,
            impervious_fraction=impervious_fraction,
            bypass_fraction=bypass_fraction,
            transit_time_days=transit_time_days,
            curve_number=None,
            runoff_time_days=3.5,
        )

        before = run_soil_balance(
            precipitation, etp, params_without_field, full_soil(params_without_field)
        )
        after = run_soil_balance(
            precipitation,
            etp,
            params_with_default_runoff_time,
            full_soil(params_with_default_runoff_time),
        )

        assert np.array_equal(before.etr, after.etr)
        assert np.array_equal(before.residual_etp, after.residual_etp)
        assert np.array_equal(before.recharge, after.recharge)
        assert np.array_equal(before.runoff, after.runoff)
        assert np.array_equal(before.soil_storage, after.soil_storage)
        assert np.array_equal(before.transit_storage, after.transit_storage)
        assert np.all(after.runoff_cn == 0.0)
