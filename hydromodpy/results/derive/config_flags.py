"""What a run kept of the per-cell budget, and what to tell a reader who misses a field.

Every derived field is rebuilt on read from the per-cell budget terms of the
store. By default a run keeps all of them, so a field is missing only because
the model does not produce it, and that is a quiet skip. With
``[simulation.results] keep_per_cell_budget = false`` a run keeps only the
terms its consumers read. A reader that then misses a field has something to
act on, and the store says which case it is: the ``policy`` and ``kept_terms``
attributes of its ``budget/`` group (:func:`hydromodpy.core.budget.terms.kept_budget`),
never the configuration.

``keep_per_cell_budget`` is the only option left. A field that reads no budget
term (a head, a static parameter) has no option.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from hydromodpy.core.budget.terms import (
    POLICY_ALL,
    POLICY_CONSUMERS,
    KeptBudget,
    budget_terms_for,
)

#: The one option of ``[simulation.results]`` that decides what the budget keeps.
KEEP_BUDGET_OPTION = "keep_per_cell_budget"


class SupportsHasField(Protocol):
    """Minimal run interface needed to tell a missing field from an absent one."""

    def has_field(self, variable: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class MissingBudget:
    """Why a run lacks fields it could have kept.

    ``kept`` is what the store declares, None for a store written before it
    declared anything. ``terms`` are the per-cell terms the missing fields read
    that the run did not keep (every term the fields read, for such a store).
    """

    kept: KeptBudget | None
    fields: tuple[str, ...]
    terms: tuple[str, ...]


def config_option_for(field: str) -> str | None:
    """Return the ``[simulation.results]`` option that keeps ``field``, or None."""
    return KEEP_BUDGET_OPTION if budget_terms_for(field) else None


def option_hint(option: str) -> str:
    """Render an option as the TOML line that sets it."""
    return f"[simulation.results] {option} = true"


def enable_options_hint(options: Iterable[str], *, level: str = "result") -> str:
    """One actionable sentence naming what to declare or set, and the re-run.

    A kept calibration trial is ``research``: it keeps only the terms its
    criterion reads whatever its configuration sets, so the sentence names
    ``hmp replay`` instead of an option a run of it never left aside.
    """
    if level == "research":
        return (
            "This run is a kept calibration trial: it keeps only the budget terms "
            "its criterion reads. hmp replay <run> writes it at the result level."
        )
    lines = ", ".join(option_hint(option) for option in options)
    return (
        "Declare a figure or an [[export]] that reads the field, or set "
        f"{lines} (the default), and run the simulation again: the per-cell budget "
        "is kept during the run, not on read."
    )


def _level_of_run(run: SupportsHasField) -> str:
    """Return the level of the run a message talks about.

    A ``Run`` reads it from its lineage. A lighter stand-in that only answers
    ``has_field`` carries no lineage and is read at the ``result`` level, like
    a run with no lineage.
    """
    from hydromodpy.results.run import Run
    from hydromodpy.results.run.sealed import lineage_of
    from hydromodpy.results.storage.kept import level_of

    if not isinstance(run, Run):
        return "result"
    return level_of(lineage_of(run))


def diagnose_missing(fields: Iterable[str], run: SupportsHasField) -> MissingBudget | None:
    """Tell whether a run lacks fields because it did not keep their budget terms.

    None when nothing is actionable: every field is present, reads no budget
    term, or reads terms the run kept (a term kept with no array is a term the
    model does not produce, which no option changes). A store that declares no
    policy (written before the attributes existed) is actionable for every
    missing field that reads a budget term: it was written before the budget
    was kept by default. Unless it holds no head: a lumped run never had a
    per-cell budget to keep, so nothing is actionable.
    """
    missing = [
        name for name in dict.fromkeys(fields) if budget_terms_for(name) and not run.has_field(name)
    ]
    if not missing:
        return None
    from hydromodpy.results.run.geographic import has_head_of, kept_budget_of

    kept = kept_budget_of(run)
    needed = {term for name in missing for term in budget_terms_for(name)}
    if kept is None:
        if not has_head_of(run):
            return None
        return MissingBudget(None, tuple(missing), tuple(sorted(needed)))
    if kept.policy != POLICY_CONSUMERS:
        return None
    lacking = needed - set(kept.terms)
    if not lacking:
        return None
    return MissingBudget(kept, tuple(missing), tuple(sorted(lacking)))


def missing_field_options(fields: Iterable[str], run: SupportsHasField) -> list[str]:
    """Options of ``[simulation.results]`` that would have kept a field ``run`` lacks.

    Separates the two reasons a consumer skips a run. A run that does not fit
    the request (no lake, no particles, another solver) misses fields no option
    controls and stays a quiet skip. A field whose budget terms the run did not
    keep is a result the run was asked for and did not store, which must be
    visible.
    """
    return [] if diagnose_missing(fields, run) is None else [KEEP_BUDGET_OPTION]


def missing_field_explanation(fields: Iterable[str], run: SupportsHasField) -> str:
    """Say what the run kept, which terms the missing fields need, and what to do.

    Empty when the miss is not actionable (see :func:`diagnose_missing`).
    """
    problem = diagnose_missing(fields, run)
    if problem is None:
        return ""
    hint = enable_options_hint([KEEP_BUDGET_OPTION], level=_level_of_run(run))
    if problem.kept is None:
        return (
            "This run was written before the per-cell budget was kept by default, so the "
            f"terms it needs ({', '.join(problem.terms)}) were not stored. {hint}"
        )
    kept = ", ".join(problem.kept.terms) or "none"
    return (
        f"This run kept only the per-cell budget terms its consumers read ({kept}); "
        f"{', '.join(problem.fields)} also needs {', '.join(problem.terms)}. {hint}"
    )


# Fields built from the water that leaves the aquifer at the surface. Their
# per-cell terms come from the one table of ``core.budget.terms``, minus the
# recharge some of them also read, which is an entry and not an exit.
_EXIT_FIELDS = (
    "release_flux",
    "release_accumulation_flux",
    "drain_accumulation_flux",
    "outflow_drain",
)


def _exit_terms_of(field: str) -> tuple[str, ...]:
    """Return the budget terms through which water leaves the aquifer for ``field``."""
    return tuple(term for term in budget_terms_for(field) if term != "recharge")


def _model_has_no_exit(run: Any, terms: tuple[str, ...], has_budget_term: bool) -> bool:
    """Say whether the run proves its model has none of the exit ``terms``.

    A store that declares its policy proves it when it kept the whole budget and
    holds some term of it (the extractors stamp ``all`` with no term when no
    budget was read, which proves nothing), or when it kept every exit term and
    wrote no array for them. A store that declares nothing is read as before:
    some budget term is there, no exit one. A plan that kept other terms only
    says nothing about the exits.
    """
    from hydromodpy.results.run.geographic import kept_budget_of

    kept = kept_budget_of(run)
    if kept is None or kept.policy == POLICY_ALL:
        return has_budget_term
    return all(term in kept.terms for term in terms)


def no_surface_exit_reason(run: Any, required_fields: Iterable[str]) -> str | None:
    """Say why a field built on the surface outflow cannot exist in ``run``, or None.

    Only answers when the store proves the model has no exit. A model without
    drain, stream, lake or surface excess releases no groundwater at the
    surface, so ``release_flux`` and the fields routed from it do not exist. No
    results option can change that, so a consumer that skips is not asked to
    act. A run that kept only the terms its consumers read (the ``consumers``
    policy) may lack the exit terms because the plan never asked for them: that
    is not "no exit", and the answer is None.
    """
    from hydromodpy.results.field_registry import FIELD_REGISTRY

    fields = [name for name in required_fields if name in _EXIT_FIELDS]
    if not fields:
        return None
    has_field = getattr(run, "has_field", None)
    if has_field is None:
        return None
    try:
        missing = [name for name in fields if not has_field(name)]
        if not missing:
            return None
        has_budget_term = any(
            has_field(name, subgroup="budget")
            for name, descriptor in FIELD_REGISTRY.items()
            if descriptor.zarr_path.startswith("budget/")
        )
        for name in missing:
            terms = _exit_terms_of(name)
            if any(has_field(term, subgroup="budget") for term in terms):
                continue
            if not _model_has_no_exit(run, terms, has_budget_term):
                return None
            exits = (
                "drain, stream, lake or surface excess"
                if name in ("release_flux", "release_accumulation_flux")
                else "drain"
            )
            return (
                f"the model has no {exits}, so no groundwater leaves the aquifer "
                f"that way and the run has no {name}"
            )
    except (TypeError, RuntimeError, KeyError, OSError):
        return None
    return None


__all__ = [
    "KEEP_BUDGET_OPTION",
    "MissingBudget",
    "SupportsHasField",
    "config_option_for",
    "diagnose_missing",
    "enable_options_hint",
    "missing_field_explanation",
    "missing_field_options",
    "no_surface_exit_reason",
    "option_hint",
]
