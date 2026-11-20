"""The per-cell budget terms a field reads, and what a store says it kept."""

from __future__ import annotations

import pytest
import zarr

from hydromodpy.core.budget.terms import (
    BUDGET_KEPT_TERMS_ATTR,
    BUDGET_POLICY_ATTR,
    PER_CELL_BUDGET_TERMS,
    POLICY_ALL,
    POLICY_CONSUMERS,
    TERM_FAMILIES,
    BudgetKeep,
    KeptBudget,
    budget_terms_for,
    kept_budget,
)
from hydromodpy.solver.modflow_common.budget_components import CANONICAL_BUDGET_TERMS

TERMS_OF_A_FIELD = [
    pytest.param("budget_flux_per_area", ("drain", "recharge"), id="flux per area"),
    pytest.param("mass_seepage", ("drain", "surface_excess"), id="mass seepage"),
    pytest.param("mass_seepage_running_sum", ("drain", "surface_excess"), id="running sum"),
    pytest.param("head", (), id="head"),
    pytest.param("watertable_elevation", (), id="watertable elevation"),
    pytest.param("watertable_depth", (), id="watertable depth"),
    pytest.param("nothing", (), id="unknown field"),
]


@pytest.mark.parametrize(("field", "terms"), TERMS_OF_A_FIELD)
def test_terms_of_a_field(field: str, terms: tuple[str, ...]) -> None:
    assert budget_terms_for(field) == terms


@pytest.mark.parametrize("term", sorted(PER_CELL_BUDGET_TERMS - {"drain"}))
def test_a_budget_term_reads_itself(term: str) -> None:
    assert budget_terms_for(term) == (term,)


def test_per_cell_terms() -> None:
    assert PER_CELL_BUDGET_TERMS == CANONICAL_BUDGET_TERMS | {
        "surface_excess",
        "constant_head_stream",
    }


@pytest.mark.parametrize("term", ["recharge", "drain", "well", "surface_excess", "constant_head"])
def test_boussinesq_terms(term: str) -> None:
    assert term in PER_CELL_BUDGET_TERMS


def test_unknown_policy() -> None:
    with pytest.raises(ValueError, match="policy"):
        BudgetKeep("some")


def test_store_without_budget_group() -> None:
    assert kept_budget(zarr.group()) is None


def test_group_without_attributes() -> None:
    root = zarr.group()
    root.create_group("budget")
    assert kept_budget(root) is None


def test_group_policy_and_sorted_terms() -> None:
    root = zarr.group()
    group = root.create_group("budget")
    group.attrs[BUDGET_POLICY_ATTR] = POLICY_CONSUMERS
    group.attrs[BUDGET_KEPT_TERMS_ATTR] = ["recharge", "drain"]
    assert kept_budget(root) == KeptBudget(POLICY_CONSUMERS, ("drain", "recharge"))


def test_group_that_kept_all() -> None:
    root = zarr.group()
    root.create_group("budget").attrs[BUDGET_POLICY_ATTR] = POLICY_ALL
    assert kept_budget(root) == KeptBudget(POLICY_ALL, ())


def test_family_members() -> None:
    for name, members in TERM_FAMILIES.items():
        assert {name, *members} <= PER_CELL_BUDGET_TERMS
