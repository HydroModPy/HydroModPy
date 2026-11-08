"""The closed set of names a solver backend lists in ``supports``: the traits of the ``Model`` it honours.

A trait is a boundary kind of ``FLOW_BOUNDARY_DEFINITIONS``, a field of
``ModelOptions`` or an initial state a TOML can choose. The names are read from
those three places and never copied, so a boundary kind or an option added there
joins the set at once. A backend that leaves a trait out is refused before the
run when the model asks for it, rather than ignoring it in the solve.
"""

from __future__ import annotations

from dataclasses import fields

from hydromodpy.model.boundaries.boundary_condition_registry import FLOW_BOUNDARY_DEFINITIONS
from hydromodpy.model.initial.state import CyclicStart, HeadRule, PriorState, SteadyStart
from hydromodpy.model.model import ModelOptions

INITIAL_STATE_TRAITS: dict[type, str] = {
    HeadRule: "head_rule",
    SteadyStart: "steady_start",
    CyclicStart: "cyclic_start",
    PriorState: "prior_state",
}
"""The trait name of each initial state a TOML can choose.

``SolvedState`` has none: an auxiliary solve returns it, and no document asks for it.
"""

SUPPORT_SOURCES: dict[str, frozenset[str]] = {
    "boundary": frozenset(FLOW_BOUNDARY_DEFINITIONS),
    "option": frozenset(field.name for field in fields(ModelOptions)),
    "initial_state": frozenset(INITIAL_STATE_TRAITS.values()),
}
"""The names of each source of traits. A new kind of trait is one more line here."""

SUPPORTS: frozenset[str] = frozenset().union(*SUPPORT_SOURCES.values())
"""Every name a backend may list in ``supports``."""


__all__ = ["INITIAL_STATE_TRAITS", "SUPPORTS", "SUPPORT_SOURCES"]
