"""Which ``[simulation.results]`` option persists which stored field.

Two kinds of option decide what a run keeps. A ``results.derived`` flag
persists one derived field: the flag and the field share a name everywhere
except the seepage mask (flag ``seepage_areas``, field ``seepage_mask``). The
raw budget fields share a single switch, ``results.budget.spatial_fields``,
and their list is read from :mod:`hydromodpy.results.field_registry` so a new
``budget/<name>`` entry is covered without touching this module.

Consumers use this map in both directions of the same question: the workflow
turns a flag on when a requested figure needs the field, and the renderer
names the option to enable when a field a figure needs is absent. The second
direction also covers a field the run computed as an intermediate and dropped
(the per-cell budget forced on by reconciliation): re-rendering it needs a new
solve, which the message has to say instead of skipping in silence.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from hydromodpy.results.field_registry import FIELD_REGISTRY

DERIVED_FIELD_FLAGS: dict[str, str] = {
    "watertable_elevation": "watertable_elevation",
    "watertable_depth": "watertable_depth",
    "seepage_mask": "seepage_areas",
    "release_flux": "release_flux",
    "accumulation_flux": "accumulation_flux",
    "release_accumulation_flux": "release_accumulation_flux",
    "outflow_drain": "outflow_drain",
    "concentration_seepage": "concentration_seepage",
    "mass_seepage": "mass_seepage",
    "mass_accumulated": "mass_accumulated",
}

# Dotted path, relative to ``[simulation.results]``, of the per-cell budget
# switch. It is the only option controlling every raw ``budget/<name>`` field.
BUDGET_SPATIAL_OPTION = "budget.spatial_fields"


def _budget_field_options() -> dict[str, str]:
    """Registry fields stored under ``budget/``, mapped to their one switch."""
    return {
        name: BUDGET_SPATIAL_OPTION
        for name, descriptor in FIELD_REGISTRY.items()
        if descriptor.zarr_path.startswith("budget/")
    }


# Every field an option of ``[simulation.results]`` decides to persist, mapped
# to that option as a dotted path.
FIELD_CONFIG_OPTIONS: dict[str, str] = {
    **{field: f"derived.{flag}" for field, flag in DERIVED_FIELD_FLAGS.items()},
    **_budget_field_options(),
}


def derived_flag_for(field: str) -> str | None:
    """Return the ``results.derived`` flag persisting ``field``, or None."""
    return DERIVED_FIELD_FLAGS.get(field)


def config_option_for(field: str) -> str | None:
    """Return the ``[simulation.results]`` option persisting ``field``, or None."""
    return FIELD_CONFIG_OPTIONS.get(field)


def option_hint(option: str) -> str:
    """Render a dotted option as the TOML line that enables it."""
    section, _, key = option.rpartition(".")
    return f"[simulation.results.{section}] {key} = true"


def enable_options_hint(options: Iterable[str]) -> str:
    """One actionable sentence naming the options to enable and the re-run."""
    lines = ", ".join(option_hint(option) for option in options)
    return (
        f"Set {lines} and run the simulation again: this field is written "
        "during the run, not on read."
    )


class SupportsHasField(Protocol):
    """Minimal run interface needed to tell a missing field from a flag-off one."""

    def has_field(self, variable: str) -> bool: ...


def missing_field_options(fields: Iterable[str], run: SupportsHasField) -> list[str]:
    """``[simulation.results]`` options that would have kept a field ``run`` lacks.

    Separates the two reasons a consumer skips a run. A run that does not
    fit the request (no lake, no particles, another solver) misses fields no
    option controls and stays a quiet skip. A field that only a disabled
    option would have kept is a result the run was asked for and did not
    store, which must be visible.
    """
    options = {
        config_option_for(name)
        for name in fields
        if config_option_for(name) is not None and not run.has_field(name)
    }
    return sorted(str(option) for option in options)


def log_missing_field(logger: Any, run: SupportsHasField, field: str, what: str) -> None:
    """Log one skipped consumer, loudly when a config option would have kept the field.

    ``what`` names the artefact that is being skipped, for example
    ``"metrics for run x"``.
    """
    options = missing_field_options([field], run)
    if options:
        logger.warning(
            "Skipping %s: field '%s' is not in the store. %s",
            what,
            field,
            enable_options_hint(options),
        )
        return
    logger.debug("Skipping %s: field '%s' is not available for this run.", what, field)


__all__ = [
    "BUDGET_SPATIAL_OPTION",
    "DERIVED_FIELD_FLAGS",
    "FIELD_CONFIG_OPTIONS",
    "SupportsHasField",
    "config_option_for",
    "derived_flag_for",
    "enable_options_hint",
    "log_missing_field",
    "missing_field_options",
    "option_hint",
]
