"""``nse_seasonal`` and the increment scores read the dates, not the position.

The pairing drops the dates where the record has no value. The kernels took
the position in the vector for the time, so past a gap the harmonics were
fitted out of phase and an increment spanned the gap as one step. Four years
of daily stage with 120 days missing: ``nse_seasonal`` went from 0.31 to 0.98,
``nse_delta`` from 0.48 to 0.95.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.criteria.series import METRICS, SeriesCriterion
from hydromodpy.calibration.metrics.scalar import score
from hydromodpy.calibration.optim.objective import ConfigBlockObjective, SimulationOutput
from hydromodpy.core.metrics import kge, kge_delta, nse_delta, nse_seasonal
from hydromodpy.results.derive.time_alignment import align_observed_simulated

YEAR = 365.25
DAYS = np.arange(4 * 365, dtype=float)
KEPT = (DAYS < 400) | (DAYS >= 520)


def _stage() -> tuple[np.ndarray, np.ndarray]:
    obs = (
        10.0
        + 3.0 * np.cos(2.0 * np.pi * DAYS / YEAR)
        + np.sin(4.0 * np.pi * DAYS / YEAR)
        + 0.5 * np.sin(DAYS / 9.0)
    )
    sim = obs + 0.3 * np.sin(DAYS / 5.0) + 0.2
    return sim, obs


def test_a_gap_keeps_the_seasonal_score_of_the_whole_record() -> None:
    sim, obs = _stage()
    whole = nse_seasonal(sim, obs, period=YEAR)

    gapped = nse_seasonal(sim[KEPT], obs[KEPT], period=YEAR, times=DAYS[KEPT])

    assert gapped == pytest.approx(whole, abs=0.02)


def test_a_nan_left_in_place_is_a_gap() -> None:
    sim, obs = _stage()
    holed = obs.copy()
    holed[~KEPT] = np.nan

    assert nse_seasonal(sim, holed, period=YEAR) == pytest.approx(
        nse_seasonal(sim[KEPT], obs[KEPT], period=YEAR, times=DAYS[KEPT])
    )


def test_an_increment_never_spans_a_gap() -> None:
    sim, obs = _stage()
    before, after = DAYS[KEPT] < 400, DAYS[KEPT] >= 520
    s, o = sim[KEPT], obs[KEPT]
    d_sim = np.concatenate([np.diff(s[before]), np.diff(s[after])])
    d_obs = np.concatenate([np.diff(o[before]), np.diff(o[after])])
    expected = 1.0 - np.sum((d_sim - d_obs) ** 2) / np.sum((d_obs - d_obs.mean()) ** 2)

    assert nse_delta(s, o, times=DAYS[KEPT]) == pytest.approx(expected)
    assert kge_delta(s, o, times=DAYS[KEPT])["kge"] == pytest.approx(kge(d_sim, d_obs)["kge"])


def test_a_regular_series_scores_as_before() -> None:
    sim, obs = _stage()

    assert nse_seasonal(sim, obs, period=YEAR, times=DAYS) == nse_seasonal(sim, obs, period=YEAR)
    assert nse_delta(sim, obs, step=10, times=DAYS) == nse_delta(sim, obs, step=10)


@pytest.mark.parametrize("metric", ["nse_seasonal", "nse_delta", "reservoir"])
def test_the_criterion_reads_the_dates(metric: str) -> None:
    sim, obs = _stage()
    criterion = SeriesCriterion(metric, METRICS[metric])
    holed = obs.copy()
    holed[~KEPT] = np.nan

    dated = criterion.score(sim[KEPT], obs[KEPT], sample_days=1.0, times_days=DAYS[KEPT])

    assert dated.cost == pytest.approx(criterion.score(sim, holed, sample_days=1.0).cost)


def test_the_single_metric_route_reads_the_gap_the_pairing_left() -> None:
    sim, obs = _stage()
    stamps = pd.date_range("2001-01-01", periods=DAYS.size, freq="D")
    record = pd.Series(np.where(KEPT, obs, np.nan), index=stamps)

    simulated = pd.Series(sim, index=stamps)

    cost = score(record, simulated, "nse_seasonal", time_method="point")

    paired = align_observed_simulated(record, simulated, method="point")
    days = paired.index.asi8 / 86_400e9
    assert days.size < DAYS.size - 100
    expected = 1.0 - nse_seasonal(paired["sim"], paired["obs"], period=YEAR, times=days)
    assert cost == pytest.approx(expected)


def test_the_block_route_reads_the_paired_dates() -> None:
    sim, obs = _stage()
    block = ConfigBlockObjective(
        name="level",
        metric="nse_seasonal",
        uses_outputs=["stage"],
        observed_by_output={"stage": obs[KEPT]},
    )
    trial = SimulationOutput(
        sim_id="",
        stations=(),
        times=np.empty(0),
        values={"stage": sim[KEPT]},
        metadata={"sample_days": {"stage": 1.0}, "sample_times": {"stage": DAYS[KEPT]}},
    )

    expected = 1.0 - nse_seasonal(sim[KEPT], obs[KEPT], period=YEAR, times=DAYS[KEPT])
    assert block.evaluate(trial).components["level.raw_cost"] == pytest.approx(expected)
