"""Per-cell budget terms: which ones a field reads, and what a store kept.

By default a run keeps the whole per-cell budget under ``budget/`` and every
derived field is rebuilt on read. With ``[simulation.results]
keep_per_cell_budget = false`` the run keeps only the terms its consumers read
(the ``"consumers"`` policy). :func:`budget_terms_for` is the table of that
policy: field name -> per-cell terms the field reads.

The store says what it kept through two attributes of the ``budget/`` group,
so a reader can tell a term that was dropped from one that is simply zero.

``BudgetKeep`` and ``kept_budget`` say which terms a store kept, so a run that dropped
the full budget still tells what it can rebuild. ``TERM_FAMILIES`` names the terms a
reader sums for one name, ``storage`` for ``storage_ss`` and ``storage_sy``. A derived
field that needs a new term adds a row to ``FIELD_TERMS``, the table behind ``budget_terms_for``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, NamedTuple

from hydromodpy.core.budget.flux import (
    DRAIN_BUDGET_KEYS,
    DRN_TO_MVR_KEYS,
    RELEASE_BUDGET_KEYS,
    STREAM_CONSTANT_HEAD_BUDGET,
)

POLICY_ALL = "all"
POLICY_CONSUMERS = "consumers"
_POLICIES = frozenset({POLICY_ALL, POLICY_CONSUMERS})

#: Attribute of the ``budget/`` group: the policy the extractor applied.
BUDGET_POLICY_ATTR = "policy"
#: Attribute of the ``budget/`` group: the terms it kept.
BUDGET_KEPT_TERMS_ATTR = "kept_terms"

#: Per-cell term written by a surface-excess solver (Boussinesq).
SURFACE_EXCESS_TERM = "surface_excess"

#: Every canonical name an extractor can write under ``budget/``: the MODFLOW
#: canonical names, the Boussinesq surface excess and the synthetic stream
#: constant head. Kept equal to the solver map by a unit test.
PER_CELL_BUDGET_TERMS: frozenset[str] = frozenset(
    {
        "recharge",
        "drain",
        "drain_to_mover",
        "lake_to_mover",
        "stream_to_mover",
        "well",
        "river",
        "constant_head",
        "evapotranspiration",
        "general_head",
        "storage",
        "storage_ss",
        "storage_sy",
        "lake",
        "stream",
        "mover",
        SURFACE_EXCESS_TERM,
        STREAM_CONSTANT_HEAD_BUDGET,
    }
)

#: A reader's name for a budget term -> the per-cell terms a solver may write for
#: it. MODFLOW 6 splits the storage of a cell into its specific storage and its
#: specific yield, MODFLOW-NWT and Boussinesq write one ``storage``. Nothing is
#: summed on write: a reader sums the members it finds.
TERM_FAMILIES: dict[str, tuple[str, ...]] = {"storage": ("storage_ss", "storage_sy")}


def family_terms(name: str, kept: Iterable[str]) -> tuple[str, ...]:
    """Return the per-cell terms a reader sums for ``name``, among the terms a run kept.

    ``name`` itself when the run kept it, else the members of its family the run
    kept (one is enough: a confined model may write only ``storage_ss``), else
    an empty tuple.
    """
    kept_names = set(kept)
    if name in kept_names:
        return (name,)
    return tuple(member for member in TERM_FAMILIES.get(name, ()) if member in kept_names)


# Synthetic term -> the CBC term its slab is built from.
_SYNTHETIC_SOURCES: dict[str, str] = {STREAM_CONSTANT_HEAD_BUDGET: "constant_head"}


@dataclass(frozen=True, slots=True)
class BudgetKeep:
    """What an extractor keeps of the per-cell budget."""

    policy: str
    terms: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.policy not in _POLICIES:
            raise ValueError(
                f"Unknown budget policy {self.policy!r}; expected one of {sorted(_POLICIES)}."
            )

    @classmethod
    def everything(cls) -> BudgetKeep:
        return cls(POLICY_ALL)

    @classmethod
    def of_terms(cls, terms: Iterable[str]) -> BudgetKeep:
        return cls(POLICY_CONSUMERS, frozenset(terms))

    def keeps(self, term: str) -> bool:
        """Return True when ``term`` is written to the store."""
        return self.policy == POLICY_ALL or term in self.terms

    def reads_record(self, term: str) -> bool:
        """Return True when the extractor must build the slab of a CBC term.

        The slab is built when the term is kept, or when it is the source of a
        kept synthetic term.
        """
        if self.keeps(term):
            return True
        return any(
            source == term and self.keeps(synthetic)
            for synthetic, source in _SYNTHETIC_SOURCES.items()
        )


class KeptBudget(NamedTuple):
    """The policy and the terms a store declares for its ``budget/`` group."""

    policy: str
    terms: tuple[str, ...]


def kept_budget(root: Any) -> KeptBudget | None:
    """Read what the ``budget/`` group of a store says it kept.

    Returns None when the group is absent or carries no policy attribute, which
    is a store written before the attributes existed.
    """
    try:
        group = root["budget"]
    except KeyError:
        return None
    attrs = group.attrs
    policy = attrs.get(BUDGET_POLICY_ATTR)
    if policy is None:
        return None
    terms = attrs.get(BUDGET_KEPT_TERMS_ATTR) or ()
    return KeptBudget(str(policy), tuple(sorted(str(t) for t in terms)))


_SEEPAGE_MASK_TERMS = (SURFACE_EXCESS_TERM,)

#: The boundary packages a cell can exchange water with, in the order of their
#: code in ``package_cells``: the code of a package is its place here plus one,
#: and a cell touched by two packages at one step takes the code after the last.
ACTING_PACKAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("well", ("well",)),
    ("drain", (*DRAIN_BUDGET_KEYS, *DRN_TO_MVR_KEYS)),
    ("general head", ("general_head",)),
    ("river", ("river",)),
    ("stream", ("stream",)),
    ("lake", ("lake",)),
    ("constant head", ("constant_head", STREAM_CONSTANT_HEAD_BUDGET)),
)

FIELD_TERMS: dict[str, tuple[str, ...]] = {
    "release_flux": (*RELEASE_BUDGET_KEYS, "recharge"),
    "release_accumulation_flux": (*RELEASE_BUDGET_KEYS, "recharge"),
    "simulated_active_network": (*RELEASE_BUDGET_KEYS, "recharge"),
    "network_agreement": (*RELEASE_BUDGET_KEYS, "recharge"),
    "downslope_distance": (*RELEASE_BUDGET_KEYS, "recharge"),
    "package_cells": tuple(term for _, terms in ACTING_PACKAGES for term in terms),
    "drain_accumulation_flux": (*DRAIN_BUDGET_KEYS, *DRN_TO_MVR_KEYS),
    "outflow_drain": (*DRAIN_BUDGET_KEYS, *DRN_TO_MVR_KEYS),
    "budget_flux_per_area": ("drain", "recharge"),
    "seepage_mask": _SEEPAGE_MASK_TERMS,
    "concentration_seepage": _SEEPAGE_MASK_TERMS,
    "mass_seepage": (*DRAIN_BUDGET_KEYS, *_SEEPAGE_MASK_TERMS),
    "mass_seepage_running_sum": (*DRAIN_BUDGET_KEYS, *_SEEPAGE_MASK_TERMS),
}
"""One row per derived field: the per-cell budget terms a run must keep to rebuild it."""


def budget_terms_for(field: str) -> tuple[str, ...]:
    """Return the sorted per-cell budget terms a field reads."""
    if field in FIELD_TERMS:
        return tuple(sorted(set(FIELD_TERMS[field])))
    if field in PER_CELL_BUDGET_TERMS:
        return (field,)
    return ()


def budget_terms_for_fields(fields: Iterable[str]) -> tuple[str, ...]:
    """Return the sorted union of the terms read by several fields."""
    return tuple(sorted({term for field in fields for term in budget_terms_for(field)}))


__all__ = [
    "ACTING_PACKAGES",
    "BUDGET_KEPT_TERMS_ATTR",
    "BUDGET_POLICY_ATTR",
    "FIELD_TERMS",
    "PER_CELL_BUDGET_TERMS",
    "POLICY_ALL",
    "POLICY_CONSUMERS",
    "SURFACE_EXCESS_TERM",
    "TERM_FAMILIES",
    "BudgetKeep",
    "KeptBudget",
    "budget_terms_for",
    "budget_terms_for_fields",
    "family_terms",
    "kept_budget",
]
