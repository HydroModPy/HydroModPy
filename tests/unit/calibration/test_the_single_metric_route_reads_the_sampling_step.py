"""The single-metric route hands the sampling step to the seasonal kernels.

``nse_seasonal`` and ``reservoir`` count one year and ten days in samples of
the series. The block route reads the step from the trial's dates; the
single-metric route (``variable`` + ``objective``) passed none, so a monthly
series was taken as daily: NaN on three years, and a refused trial, where the
block route scores a number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.criteria.series import METRICS, SeriesCriterion
from hydromodpy.calibration.metrics.scalar import score

STAMPS = pd.date_range("2001-01-31", periods=36, freq="ME")
STEP_DAYS = float(np.median(np.diff(STAMPS.asi8) / 86_400e9))


def _monthly() -> tuple[pd.Series, pd.Series]:
    months = np.arange(STAMPS.size, dtype=float)
    obs = 10.0 + 3.0 * np.cos(2.0 * np.pi * months / 12.0) + 0.5 * np.sin(months)
    sim = obs + 0.2 * np.cos(3.0 * months)
    return pd.Series(obs, index=STAMPS), pd.Series(sim, index=STAMPS)


@pytest.mark.parametrize("metric", ["nse_seasonal", "reservoir"])
def test_a_monthly_series_scores_as_on_the_block_route(metric: str) -> None:
    observed, simulated = _monthly()

    cost = score(observed, simulated, metric, time_method="point")

    block = SeriesCriterion(metric, METRICS[metric]).score(
        simulated.to_numpy(),
        observed.to_numpy(),
        sample_days=STEP_DAYS,
        times_days=STAMPS.asi8 / 86_400e9,
    )
    assert np.isfinite(cost)
    assert cost == pytest.approx(block.cost)


def test_a_daily_series_keeps_its_daily_score() -> None:
    stamps = pd.date_range("2001-01-01", periods=3 * 365, freq="D")
    days = np.arange(stamps.size, dtype=float)
    obs = pd.Series(
        5.0 + np.cos(2.0 * np.pi * days / 365.25) + 0.1 * np.sin(days / 7.0), index=stamps
    )
    sim = obs + 0.05 * np.sin(days / 3.0)

    cost = score(obs, sim, "nse_seasonal", time_method="point")

    undated = SeriesCriterion("nse_seasonal", METRICS["nse_seasonal"]).score(
        sim.to_numpy(), obs.to_numpy()
    )
    assert cost == pytest.approx(undated.cost, abs=1e-3)


def test_the_step_is_the_median_spacing_in_days() -> None:
    from hydromodpy.calibration.metrics.scalar import sampling_step_days

    assert sampling_step_days(pd.date_range("2001-01-01", periods=5, freq="D")) == 1.0
    assert sampling_step_days(pd.DatetimeIndex(["2001-01-01"])) is None
    assert sampling_step_days(pd.RangeIndex(4)) is None
