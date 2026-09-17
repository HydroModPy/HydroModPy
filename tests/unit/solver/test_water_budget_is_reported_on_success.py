"""A run that converges still has to say how well its water budget closed.

``PERCENT DISCREPANCY`` was read only when the solver reported failure, as
context for the error message. A run that converges and writes heads with a
twelve percent imbalance was therefore an ordinary trial: scored, compared and
promoted like any other, with nothing anywhere saying its mass balance did not
close. Convergence and a closed budget are two different questions.

Reported as a run metric rather than enforced here: what an unacceptable
discrepancy is belongs to whoever reads the number, and a calibration that
silently dropped trials would be a worse failure than one that reports them.

The number also has to be the worst one, not the last one. A transient run that
loses its budget in the middle and recovers by the final time step prints a clean
final block, so reading only that block is reading the one moment the run had
nothing to hide.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.solver.modflow_common.flow_adapter_helpers import (
    WATER_BUDGET_METRIC,
    WATER_BUDGET_WORST_METRIC,
    last_percent_discrepancy,
    percent_discrepancies,
    worst_percent_discrepancy,
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


_TRANSIENT_LISTING = """\
                  VOLUMETRIC BUDGET FOR ENTIRE MODEL AT END OF TIME STEP 1
   PERCENT DISCREPANCY =           0.01     PERCENT DISCREPANCY =           0.02
                  VOLUMETRIC BUDGET FOR ENTIRE MODEL AT END OF TIME STEP 2
   PERCENT DISCREPANCY =          -0.74     PERCENT DISCREPANCY =        -200.00
                  VOLUMETRIC BUDGET FOR ENTIRE MODEL AT END OF TIME STEP 3
   PERCENT DISCREPANCY =          -1.65     PERCENT DISCREPANCY =          -0.30
"""


def test_the_worst_discrepancy_is_not_the_last_one(tmp_path: Path) -> None:
    """A run that loses its budget mid-way and recovers still has to say so."""
    (tmp_path / "model.lst").write_text(_TRANSIENT_LISTING, encoding="utf-8")

    assert last_percent_discrepancy(tmp_path) == -0.30
    assert worst_percent_discrepancy(tmp_path) == -200.00


def test_the_worst_discrepancy_keeps_its_sign(tmp_path: Path) -> None:
    """Magnitude picks the value; the sign says which way the water went."""
    (tmp_path / "model.lst").write_text(
        "   PERCENT DISCREPANCY =   3.0\n   PERCENT DISCREPANCY =  -9.0\n",
        encoding="utf-8",
    )

    assert worst_percent_discrepancy(tmp_path) == -9.0


def test_both_columns_of_a_budget_block_are_read(tmp_path: Path) -> None:
    """MODFLOW prints cumulative volumes and rates side by side, both count."""
    (tmp_path / "model.lst").write_text(_TRANSIENT_LISTING, encoding="utf-8")

    assert percent_discrepancies(tmp_path) == [0.01, 0.02, -0.74, -200.00, -1.65, -0.30]


def test_a_directory_without_a_listing_has_no_worst(tmp_path: Path) -> None:
    """Absent is not zero: a backend that writes no listing reports nothing."""
    assert worst_percent_discrepancy(tmp_path) is None
    assert percent_discrepancies(tmp_path) == []


def test_a_near_zero_flow_step_is_reported_like_any_other(tmp_path: Path) -> None:
    """Nothing filters the number, because nothing acts on it.

    A percent discrepancy divides by the mean of inflow and outflow, so a step
    that routes almost no water reads large on a negligible imbalance. The
    reading is recorded as it stands; a guard that rejected on it would refuse
    sound runs, and that guard needs the absolute imbalance, not this quotient.
    """
    (tmp_path / "model.lst").write_text(
        "   PERCENT DISCREPANCY =   0.01     PERCENT DISCREPANCY =  -200.00\n",
        encoding="utf-8",
    )

    assert worst_percent_discrepancy(tmp_path) == -200.00


def test_the_worst_metric_has_one_name() -> None:
    """The name is shared so a report and a trial record agree on it."""
    assert WATER_BUDGET_WORST_METRIC == "water_budget_worst_percent_discrepancy"
