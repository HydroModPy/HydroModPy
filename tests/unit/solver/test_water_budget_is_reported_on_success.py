"""A run that converges still has to say how well its water budget closed.

``PERCENT DISCREPANCY`` was read only when the solver reported failure, as
context for the error message. A run that converges and writes heads with a
twelve percent imbalance was therefore an ordinary trial: scored, compared and
promoted like any other, with nothing anywhere saying its mass balance did not
close. Convergence and a closed budget are two different questions.

Reported as a run metric rather than enforced here: what an unacceptable
discrepancy is belongs to whoever reads the number, and a calibration that
silently dropped trials would be a worse failure than one that reports them.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.solver.modflow_common.flow_adapter_helpers import (
    WATER_BUDGET_METRIC,
    last_percent_discrepancy,
)

_LISTING = """\
                  VOLUMETRIC BUDGET FOR ENTIRE MODEL
                     IN                     OUT
                 -------                 -------
   PERCENT DISCREPANCY =           0.01
                  VOLUMETRIC BUDGET FOR ENTIRE MODEL
   PERCENT DISCREPANCY =         -12.34
"""


def test_the_last_discrepancy_of_the_run_is_the_one_read(tmp_path: Path) -> None:
    """A transient listing repeats the block; the final one is the run's."""
    (tmp_path / "model.lst").write_text(_LISTING, encoding="utf-8")

    assert last_percent_discrepancy(tmp_path) == -12.34


def test_the_simulation_listing_is_not_a_model_listing(tmp_path: Path) -> None:
    """``mfsim.lst`` carries no budget of its own."""
    (tmp_path / "mfsim.lst").write_text(_LISTING, encoding="utf-8")

    assert last_percent_discrepancy(tmp_path) is None


def test_a_directory_without_a_listing_reports_nothing(tmp_path: Path) -> None:
    """A backend that writes no listing is not a failure, it is silent."""
    assert last_percent_discrepancy(tmp_path) is None


def test_the_metric_has_one_name() -> None:
    """The name is shared so a report and a trial record agree on it."""
    assert WATER_BUDGET_METRIC == "water_budget_percent_discrepancy"
