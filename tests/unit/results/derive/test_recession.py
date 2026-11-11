"""The recession of a run is read in m3/day, from a flux that leaves the domain as a positive number.

A budget row holds ``flux_out`` in m3/s, positive when water leaves. The recession plane
is written on a volume-per-day clock, so the rate is read in m3/day and the slope of a
falling limb is positive.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.scope import DOMAIN
from hydromodpy.results.derive.recession import (
    BOUSSINESQ_LATE_TIME_CONSTANT,
    brutsaert_nieber_coefficient,
    budget_outflow_per_day,
    recession_cloud,
)

_DAYS = pd.date_range("2020-01-01", periods=4, freq="D")


def _run(rows: pd.DataFrame) -> SimpleNamespace:
    return SimpleNamespace(sim_id="sim", budget=lambda component: rows, time_index=_DAYS)


def _rows(flux_out, *, zone=DOMAIN) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestep": range(len(flux_out)),
            "zone_id": zone,
            "component": "constant_head",
            "flux_out": flux_out,
        }
    )


# One row per case: the flux_out of each step in m3/s and the outflow in m3/day.
# One m3/s is 86 400 m3/day.
_OUTFLOWS = [
    pytest.param([1.0, 0.5, 0.0, 2.0], [86400.0, 43200.0, 0.0, 172800.0], id="m3_s_to_m3_day"),
    pytest.param([1.0e-3] * 4, [86.4] * 4, id="one_liter_per_second"),
    pytest.param([0.0] * 4, [0.0] * 4, id="no_outflow"),
]


@pytest.mark.parametrize(("flux_out", "per_day"), _OUTFLOWS)
def test_a_flux_out_in_m3_per_second_is_an_outflow_in_m3_per_day(flux_out, per_day) -> None:
    series = budget_outflow_per_day(_run(_rows(flux_out)), "constant_head")

    np.testing.assert_allclose(series.to_numpy(), per_day, rtol=1e-12)
    assert (series.to_numpy() >= 0.0).all()
    assert series.index.equals(_DAYS)


def test_the_whole_domain_zone_wins_over_another_zone() -> None:
    rows = pd.concat([_rows([1.0] * 4, zone="catchment"), _rows([2.0] * 4)], ignore_index=True)

    series = budget_outflow_per_day(_run(rows), "constant_head")

    assert series.tolist() == [172800.0] * 4


def test_a_component_with_no_row_is_refused() -> None:
    with pytest.raises(ValueError, match="is empty for sim sim"):
        budget_outflow_per_day(_run(_rows([])), "constant_head")


# One row per limb: the discharge (m3/day) one value per day, the Q taken at the midpoint of
# each falling step and the slope -dQ/dt in m3/day/day, positive on a fall.
_LIMBS = [
    pytest.param([10.0, 8.0, 6.0, 5.0], [9.0, 7.0, 5.5], [2.0, 2.0, 1.0], id="a_falling_limb"),
    pytest.param([10.0, 12.0, 6.0, 7.0], [9.0], [6.0], id="a_rise_carries_no_recession"),
    pytest.param([5.0, 5.0, 5.0, 5.0], [], [], id="a_flat_limb_has_no_slope"),
]


@pytest.mark.parametrize(("discharge", "q", "slope"), _LIMBS)
def test_the_cloud_keeps_the_falling_steps_with_a_positive_slope(discharge, q, slope) -> None:
    flow, rate = recession_cloud(pd.Series(discharge, index=_DAYS))

    np.testing.assert_allclose(flow, q, rtol=1e-12)
    np.testing.assert_allclose(rate, slope, rtol=1e-12)


def test_the_head_of_the_chronicle_can_be_skipped() -> None:
    flow, _ = recession_cloud(pd.Series([10.0, 8.0, 6.0, 5.0], index=_DAYS), skip=1)

    np.testing.assert_allclose(flow, [7.0, 5.5])


def test_a_chronicle_of_under_three_values_has_no_cloud() -> None:
    flow, rate = recession_cloud(pd.Series([2.0, 1.0], index=_DAYS[:2]))

    assert flow.size == 0 and rate.size == 0


def test_the_coefficient_is_written_for_a_reach_drained_from_both_banks() -> None:
    # a = 4.804 * sqrt(4) * 100 / (0.25 * 1e4^1.5) for K = 4 m/day, L = 100 m, f = 0.25,
    # A = 1e4 m2.
    expected = BOUSSINESQ_LATE_TIME_CONSTANT * 2.0 * 100.0 / (0.25 * 1.0e6)
    kwargs = {"k": 4.0, "porosity": 0.25, "stream_length": 100.0, "area": 1.0e4}

    assert brutsaert_nieber_coefficient(**kwargs) == pytest.approx(expected)
    assert brutsaert_nieber_coefficient(**kwargs, sides=1) == pytest.approx(expected / 2.0)
