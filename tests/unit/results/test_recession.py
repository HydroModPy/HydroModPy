"""The recession cloud and the Brutsaert-Nieber coefficient a recession figure draws."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.scope import DOMAIN
from hydromodpy.results.derive.recession import (
    BOUSSINESQ_LATE_TIME_CONSTANT,
    SECONDS_PER_DAY,
    brutsaert_nieber_coefficient,
    budget_outflow_per_day,
    recession_cloud,
)


@pytest.mark.parametrize("sides", [2, 1])
def test_the_coefficient_follows_the_late_time_boussinesq_law(sides: int) -> None:
    k, porosity, length, area = 4.0, 0.05, 1000.0, 1.0e6
    symmetric = BOUSSINESQ_LATE_TIME_CONSTANT * 2.0 * length / (porosity * area**1.5)

    a = brutsaert_nieber_coefficient(
        k=k, porosity=porosity, stream_length=length, area=area, sides=sides
    )

    assert a == pytest.approx(symmetric * sides / 2.0)


def test_an_exponential_recession_gives_a_rate_proportional_to_the_discharge() -> None:
    days = pd.date_range("2020-01-01", periods=30, freq="D")
    discharge = pd.Series(100.0 * np.exp(-0.1 * np.arange(30)), index=days)

    flow, rate = recession_cloud(discharge)

    assert flow.size == 29
    assert np.allclose(rate / flow, rate[0] / flow[0])


def test_a_rising_limb_and_the_skipped_head_carry_no_recession() -> None:
    discharge = pd.Series([1.0, 2.0, 3.0, 2.5, 2.0, 2.2], index=np.arange(6.0))

    flow, rate = recession_cloud(discharge, skip=1)

    assert flow.tolist() == pytest.approx([2.75, 2.25])
    assert rate.tolist() == pytest.approx([0.5, 0.5])
    assert recession_cloud(discharge.iloc[:2])[0].size == 0


def test_the_budget_outflow_is_read_on_the_domain_zone_in_m3_per_day() -> None:
    rows = pd.DataFrame(
        {
            "zone_id": [DOMAIN, DOMAIN, "other"],
            "timestep": [1, 0, 0],
            "flux_out": [2.0, 1.0, 9.0],
        }
    )
    index = pd.date_range("2020-01-01", periods=2, freq="D")
    run = SimpleNamespace(budget=lambda component: rows, time_index=index, sim_id="s")

    series = budget_outflow_per_day(run, "constant_head")

    assert series.tolist() == [1.0 * SECONDS_PER_DAY, 2.0 * SECONDS_PER_DAY]
    assert list(series.index) == list(index)


def test_an_empty_budget_component_is_refused() -> None:
    run = SimpleNamespace(budget=lambda component: pd.DataFrame(), sim_id="s")

    with pytest.raises(ValueError, match="is empty"):
        budget_outflow_per_day(run, "constant_head")
