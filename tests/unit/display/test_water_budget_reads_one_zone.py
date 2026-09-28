"""``water_budget`` reads one budget zone, never sums the domain and the catchment.

``budgets`` may hold a whole-model-domain row (``zone_id="0"``) and a
delineated-catchment row for the same component and timestep. A plain
``groupby("component")`` over both double-counts the water: the catchment is
a subset of the domain.
"""

from __future__ import annotations

import pandas as pd
import pytest

from hydromodpy.display.figures.water_budget import WaterBudget


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


class _BudgetRun:
    sim_id = "sim-a"
    name = "nancon"

    def budget(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "component": ["recharge", "drain"],
                "timestep": [0, 0],
                "flux_in": [3.0, 0.0],
                "flux_out": [0.0, 1.0],
            }
        )


class _ZonedBudgetRun:
    sim_id = "sim-b"
    name = "nancon"

    def budget(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "component": ["recharge", "recharge"],
                "zone_id": ["0", "catchment"],
                "timestep": [0, 0],
                "flux_in": [1.093, 0.586],
                "flux_out": [0.0, 0.0],
            }
        )


def test_a_budget_without_a_zone_column_is_read_whole(mpl) -> None:
    fig, ax = mpl.subplots()

    WaterBudget().render(_BudgetRun(), ax)

    assert ax.containers
    assert "frame: the model domain" in ax.get_title()


def _bar_height(ax, label: str) -> float:
    container = next(item for item in ax.containers if item.get_label() == label)
    return float(container.datavalues[0])


def test_the_catchment_zone_is_read_not_the_domain_sum(mpl) -> None:
    # Before the fix, groupby("component") summed both zones: 1.093 + 0.586
    # m3/s of recharge, a domain total no gauge at the outlet ever sees.
    fig, ax = mpl.subplots()

    WaterBudget().render(_ZonedBudgetRun(), ax)

    assert _bar_height(ax, "flux_in") == pytest.approx(0.586)
    assert "frame: the delineated catchment" in ax.get_title()
