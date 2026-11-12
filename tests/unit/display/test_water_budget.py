"""``water_budget`` reads one budget zone and never sums the domain and the catchment.

``budgets`` may hold a whole-model-domain row (``zone_id="domain"``) and a
delineated-catchment row for the same component and timestep. The catchment is a
subset of the domain, so adding both would count the same water twice. Fluxes are in m3/s.
"""

from __future__ import annotations

import pandas as pd
import pytest

from hydromodpy.display.figures.water_budget import WaterBudget, _budget_unit_label


class BudgetRun:
    sim_id = "sim-a"
    name = "nancon"

    def __init__(self, budget: pd.DataFrame) -> None:
        self._budget = budget

    def budget(self) -> pd.DataFrame:
        return self._budget


def recharge_and_drain(**extra) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "component": ["recharge", "drain"],
            "timestep": [0, 0],
            "flux_in": [3.0, 0.0],
            "flux_out": [0.0, 1.0],
            **extra,
        }
    )


def recharge_in_two_zones() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "component": ["recharge", "recharge"],
            "zone_id": ["domain", "catchment"],
            "timestep": [0, 0],
            "flux_in": [1.093, 0.586],  # m3/s
            "flux_out": [0.0, 0.0],
        }
    )


def bar_height(ax, label: str) -> float:
    container = next(item for item in ax.containers if item.get_label() == label)
    return float(container.datavalues[0])


def test_budget_without_zone_read_whole(mpl):
    fig, ax = mpl.subplots()

    WaterBudget().render(BudgetRun(recharge_and_drain()), ax)

    assert ax.containers
    assert "frame: the model domain" in ax.get_title()


def test_catchment_zone_not_domain_sum(mpl):
    # Summing both zones would give 1.093 + 0.586 m3/s of recharge, a total no
    # gauge at the outlet ever sees.
    fig, ax = mpl.subplots()

    WaterBudget().render(BudgetRun(recharge_in_two_zones()), ax)

    assert bar_height(ax, "flux_in") == pytest.approx(0.586)
    assert "frame: the delineated catchment" in ax.get_title()


def test_units_in_the_label(mpl):
    fig, ax = mpl.subplots()
    budget = recharge_and_drain(unit=["m3/s", "m3/s"])

    WaterBudget().render(BudgetRun(budget), ax)

    assert "m3/s" in ax.get_ylabel()
    assert _budget_unit_label(budget) == "m3/s"
    assert _budget_unit_label(pd.DataFrame({"unit": ["m3/s", "m/day"]})) == "mixed units"
