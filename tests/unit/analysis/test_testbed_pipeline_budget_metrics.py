"""``_extract_budget_metrics`` reads one budget zone, never sums the domain and
the catchment.

``budgets`` may hold a whole-model-domain row (``zone_id="0"``) and a
delineated-catchment row for the same component and timestep. A plain
``groupby("component")`` over both double-counts the water: the catchment is
a subset of the domain.
"""

from __future__ import annotations

import pandas as pd
import pytest

from hydromodpy.analysis.testbed.pipeline import _extract_budget_metrics  # noqa: F401


class _ZonedBudgetRun:
    def budget(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "component": ["recharge", "recharge"],
                "zone_id": ["0", "catchment"],
                "flux_in": [1.093, 0.586],
                "flux_out": [0.0, 0.0],
            }
        )


class _DomainOnlyBudgetRun:
    def budget(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "component": ["recharge"],
                "zone_id": ["0"],
                "flux_in": [1.093],
                "flux_out": [0.0],
            }
        )


def test_the_catchment_zone_is_read_not_the_domain_sum() -> None:
    # Before the fix, groupby("component") summed both zones: 1.093 + 0.586
    # m3/s of recharge, a domain total no gauge at the outlet ever sees.
    summary, metrics = _extract_budget_metrics(_ZonedBudgetRun())

    assert summary["recharge"]["total_in"] == pytest.approx(0.586)
    assert metrics["budget_recharge_total_in"] == pytest.approx(0.586)


def test_the_domain_zone_is_read_when_no_catchment_row_exists() -> None:
    summary, metrics = _extract_budget_metrics(_DomainOnlyBudgetRun())

    assert summary["recharge"]["total_in"] == pytest.approx(1.093)
    assert metrics["budget_recharge_total_in"] == pytest.approx(1.093)
