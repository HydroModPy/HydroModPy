"""What a run kept of the per-cell budget, and what to tell a reader who misses a field.

Every derived field is rebuilt on read from the per-cell budget terms of the
store. By default a run keeps all of them, so a field is missing only because
the model does not produce it, and that is a quiet skip. With
``[simulation.results] keep_per_cell_budget = false`` a run keeps only the
terms its consumers read. A reader that then misses a field has something to
act on, and the store says which case it is: the ``policy`` and ``kept_terms``
attributes of its ``budget/`` group (:func:`hydromodpy.core.budget_terms.kept_budget`),
never the configuration.

``keep_per_cell_budget`` is the only option left. A field that reads no budget
term (a head, a static parameter) has no option.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from hydromodpy.core.budget_terms import (
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


def enable_options_hint(options: Iterable[str]) -> str:
    """One actionable sentence naming what to declare or set, and the re-run."""
    lines = ", ".join(option_hint(option) for option in options)
    return (
        "Declare a figure or an [[export]] that reads the field, or set "
        f"{lines} (the default), and run the simulation again: the per-cell budget "
        "is kept during the run, not on read."
    )


def _kept_budget(run: Any) -> KeptBudget | None:
    """What the ``budget/`` group of the store of ``run`` says it kept."""
    from hydromodpy.results.run.geographic import kept_budget_of

    return kept_budget_of(run)


def _has_head(run: Any) -> bool:
    """Whether the store of ``run`` holds a head, so that it could hold a per-cell budget."""
    from hydromodpy.results.run.geographic import has_head_of

    return has_head_of(run)


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
    kept = _kept_budget(run)
    needed = {term for name in missing for term in budget_terms_for(name)}
    if kept is None:
        if not _has_head(run):
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
    hint = enable_options_hint([KEEP_BUDGET_OPTION])
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


def log_missing_field(logger: Any, run: SupportsHasField, field: str, what: str) -> None:
    """Log one skipped consumer, loudly when the run did not keep what the field reads.

    ``what`` names the artefact that is being skipped, for example
    ``"metrics for run x"``.
    """
    explanation = missing_field_explanation([field], run)
    if explanation:
        logger.warning("Skipping %s: field '%s' is not in the store. %s", what, field, explanation)
        return
    logger.debug("Skipping %s: field '%s' is not available for this run.", what, field)


__all__ = [
    "KEEP_BUDGET_OPTION",
    "MissingBudget",
    "SupportsHasField",
    "config_option_for",
    "diagnose_missing",
    "enable_options_hint",
    "log_missing_field",
    "missing_field_explanation",
    "missing_field_options",
    "option_hint",
]
