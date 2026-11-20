"""Percent discrepancy of the water budget, read from the listing file of a run (percent).

A run that converges can still close its budget badly, so the discrepancy is reported as a
metric of the run and never enforced here. The worst value counts, not the last one, because a
run that loses its budget mid-way and recovers prints a clean final block. MODFLOW prints
cumulative volumes and rates side by side, so both columns are read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.solver.base.plan import WATER_BUDGET_METRIC, WATER_BUDGET_WORST_METRIC
from hydromodpy.solver.modflow_common.listing import (
    last_percent_discrepancy,
    percent_discrepancies,
    worst_percent_discrepancy,
)

TRANSIENT_LISTING = """\
                  VOLUMETRIC BUDGET FOR ENTIRE MODEL AT END OF TIME STEP 1
   PERCENT DISCREPANCY =           0.01     PERCENT DISCREPANCY =           0.02
                  VOLUMETRIC BUDGET FOR ENTIRE MODEL AT END OF TIME STEP 2
   PERCENT DISCREPANCY =          -0.74     PERCENT DISCREPANCY =        -200.00
                  VOLUMETRIC BUDGET FOR ENTIRE MODEL AT END OF TIME STEP 3
   PERCENT DISCREPANCY =          -1.65     PERCENT DISCREPANCY =          -0.30
"""


# The names are shared so a report and a trial record agree on them.
def test_metric_name() -> None:
    assert WATER_BUDGET_METRIC == "water_budget_percent_discrepancy"


def test_worst_metric_name() -> None:
    assert WATER_BUDGET_WORST_METRIC == "water_budget_worst_percent_discrepancy"


def test_worst_is_not_the_last(tmp_path: Path) -> None:
    (tmp_path / "model.lst").write_text(TRANSIENT_LISTING, encoding="utf-8")

    assert last_percent_discrepancy(tmp_path) == -0.30
    assert worst_percent_discrepancy(tmp_path) == -200.00


def test_worst_keeps_its_sign(tmp_path: Path) -> None:
    # The magnitude picks the value and the sign says which way the water went.
    (tmp_path / "model.lst").write_text(
        "   PERCENT DISCREPANCY =   3.0\n   PERCENT DISCREPANCY =  -9.0\n", encoding="utf-8"
    )

    assert worst_percent_discrepancy(tmp_path) == -9.0


def test_both_columns_are_read(tmp_path: Path) -> None:
    (tmp_path / "model.lst").write_text(TRANSIENT_LISTING, encoding="utf-8")

    assert percent_discrepancies(tmp_path) == [0.01, 0.02, -0.74, -200.00, -1.65, -0.30]


def test_no_listing_has_no_worst(tmp_path: Path) -> None:
    # A backend that writes no listing reports nothing, which is not zero.
    assert worst_percent_discrepancy(tmp_path) is None
    assert percent_discrepancies(tmp_path) == []
