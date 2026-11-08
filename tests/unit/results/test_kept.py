"""What a run keeps of its solver outputs, built from ``[simulation.results]``."""

from __future__ import annotations

import dataclasses

import pytest

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.results_config import ResultsConfig

# The budget the planning keeps for each value of keep_per_cell_budget: every term,
# or the terms the consumers of the run read.
EVERYTHING = BudgetKeep.everything()
CONSUMERS = BudgetKeep.of_terms({"drain", "recharge"})

KEYS = (
    ("per-cell budget kept, solver files dropped", True, False, EVERYTHING),
    ("per-cell budget kept, solver files kept", True, True, EVERYTHING),
    ("consumer terms only, solver files dropped", False, False, CONSUMERS),
    ("consumer terms only, solver files kept", False, True, CONSUMERS),
)


@pytest.mark.parametrize(
    ("case", "per_cell", "solver_files", "budget"), KEYS, ids=[c for c, *_ in KEYS]
)
def test_a_retention_reads_the_keys_of_the_results_table(
    case: str, per_cell: bool, solver_files: bool, budget: BudgetKeep
) -> None:
    del case
    results = ResultsConfig(keep_per_cell_budget=per_cell, keep_solver_files=solver_files)

    retention = Retention.of(results, budget)

    assert retention.budget is budget
    assert retention.solver_files is solver_files
    assert retention.budget.keeps("storage_ss") is per_cell
    assert retention.budget.keeps("drain")


def test_the_defaults_keep_every_term_and_drop_the_solver_files() -> None:
    retention = Retention.of(ResultsConfig(), EVERYTHING)

    assert retention == Retention(budget=EVERYTHING, solver_files=False)


@pytest.mark.parametrize(
    ("members", "named"),
    [
        ({"budget": {"drain"}, "solver_files": False}, "budget"),
        ({"budget": EVERYTHING, "solver_files": "yes"}, "solver_files"),
    ],
    ids=["a budget that is not a BudgetKeep", "solver files that are not a bool"],
)
def test_a_retention_refuses_a_member_of_the_wrong_type(members: dict, named: str) -> None:
    with pytest.raises(TypeError, match=f"Retention.{named}"):
        Retention(**members)


def test_a_retention_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        Retention(budget=EVERYTHING).solver_files = True  # type: ignore[misc]
