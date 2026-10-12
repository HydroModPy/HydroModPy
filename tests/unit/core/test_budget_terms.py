"""The per-cell budget terms a field reads, and what a store says it kept."""

from __future__ import annotations

import pytest
import zarr

from hydromodpy.core.budget_terms import (
    BUDGET_KEPT_TERMS_ATTR,
    BUDGET_POLICY_ATTR,
    PER_CELL_BUDGET_TERMS,
    POLICY_ALL,
    POLICY_CONSUMERS,
    BudgetKeep,
    KeptBudget,
    budget_terms_for,
    budget_terms_for_fields,
    kept_budget,
)
from hydromodpy.core.field_routing import RELEASE_BUDGET_KEYS
from hydromodpy.solver.modflow_common.budget_components import CANONICAL_BUDGET_TERMS


@pytest.mark.parametrize(
    "field", ["release_flux", "release_accumulation_flux", "simulated_active_network"]
)
def test_a_release_field_reads_the_release_terms_and_recharge(field: str) -> None:
    assert budget_terms_for(field) == tuple(sorted({*RELEASE_BUDGET_KEYS, "recharge"}))


@pytest.mark.parametrize("field", ["accumulation_flux", "outflow_drain"])
def test_a_drain_field_reads_the_drain_and_its_mover(field: str) -> None:
    assert budget_terms_for(field) == ("drain", "drain_to_mover")


def test_fluxes_from_budget_reads_drain_and_recharge() -> None:
    assert budget_terms_for("fluxes_from_budget") == ("drain", "recharge")


@pytest.mark.parametrize("field", ["seepage_mask", "concentration_seepage"])
def test_a_seepage_field_reads_the_surface_excess(field: str) -> None:
    assert budget_terms_for(field) == ("surface_excess",)


@pytest.mark.parametrize("field", ["mass_seepage", "mass_accumulated"])
def test_a_mass_field_reads_the_drain_and_the_surface_excess(field: str) -> None:
    assert budget_terms_for(field) == ("drain", "surface_excess")


@pytest.mark.parametrize("term", sorted(PER_CELL_BUDGET_TERMS - {"drain"}))
def test_a_budget_term_reads_itself(term: str) -> None:
    assert budget_terms_for(term) == (term,)


@pytest.mark.parametrize("field", ["head", "watertable_elevation", "watertable_depth", "nothing"])
def test_a_field_without_budget_reads_no_term(field: str) -> None:
    assert budget_terms_for(field) == ()


def test_the_terms_of_several_fields_are_their_sorted_union() -> None:
    assert budget_terms_for_fields(["fluxes_from_budget", "seepage_mask", "head"]) == (
        "drain",
        "recharge",
        "surface_excess",
    )
    assert budget_terms_for_fields([]) == ()


def test_the_per_cell_terms_are_the_solver_names_plus_two() -> None:
    assert PER_CELL_BUDGET_TERMS == CANONICAL_BUDGET_TERMS | {
        "surface_excess",
        "constant_head_stream",
    }


@pytest.mark.parametrize("term", ["recharge", "drain", "well", "surface_excess", "constant_head"])
def test_the_boussinesq_terms_are_per_cell_terms(term: str) -> None:
    assert term in PER_CELL_BUDGET_TERMS


def test_keeping_everything_keeps_every_term() -> None:
    keep = BudgetKeep.everything()
    assert keep.policy == POLICY_ALL
    assert all(keep.keeps(t) and keep.reads_record(t) for t in PER_CELL_BUDGET_TERMS)


def test_the_consumers_policy_keeps_only_its_terms() -> None:
    keep = BudgetKeep.of_terms(["drain", "recharge"])
    assert keep.policy == POLICY_CONSUMERS
    assert keep.keeps("drain")
    assert not keep.keeps("well")
    assert not keep.reads_record("well")


def test_the_stream_constant_head_needs_the_constant_head_record() -> None:
    keep = BudgetKeep.of_terms(["constant_head_stream"])
    assert keep.reads_record("constant_head")
    assert not keep.keeps("constant_head")
    assert not BudgetKeep.of_terms(["drain"]).reads_record("constant_head")


def test_an_unknown_policy_is_refused() -> None:
    with pytest.raises(ValueError, match="policy"):
        BudgetKeep("some")


def test_a_store_without_budget_group_declares_nothing() -> None:
    assert kept_budget(zarr.group()) is None


def test_a_budget_group_without_attributes_declares_nothing() -> None:
    root = zarr.group()
    root.create_group("budget")
    assert kept_budget(root) is None


def test_a_budget_group_declares_its_policy_and_sorted_terms() -> None:
    root = zarr.group()
    group = root.create_group("budget")
    group.attrs[BUDGET_POLICY_ATTR] = POLICY_CONSUMERS
    group.attrs[BUDGET_KEPT_TERMS_ATTR] = ["recharge", "drain"]
    assert kept_budget(root) == KeptBudget(POLICY_CONSUMERS, ("drain", "recharge"))


def test_a_budget_group_that_kept_all_lists_no_term() -> None:
    root = zarr.group()
    root.create_group("budget").attrs[BUDGET_POLICY_ATTR] = POLICY_ALL
    assert kept_budget(root) == KeptBudget(POLICY_ALL, ())
