"""What a backend can serve, in three states rather than two.

A yes-or-no answer is wrong here, and the reason is not fussiness. Whether a
backend can serve an observable is not a property of its class: it depends on the
packages the RESOLVED configuration builds. MODFLOW 6 can hand back a lake stage,
but only if the file actually declares a lake; MODFLOW-NWT never can, because it
builds no LAK package at all. Collapsing those two into "no" tells a user to
change backend when they only had to declare a lake, and collapsing them into
"yes" postpones the refusal to the first extraction, hours in.

So three states. Servable now. Servable once the configuration declares what it
needs, with the sentence saying what to declare. Unavailable on this backend, and
no configuration will change that.

The precedent is deliberate: this is the shape
``boundary_condition_registry.supported_backends`` already uses, consulted by the
configuration validator rather than discovered at run time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

State = Literal["servable", "servable_under_condition", "unavailable"]


@dataclass(frozen=True)
class ObservableSupport:
    """Whether one named observable can be served, and what it would take."""

    name: str
    state: State
    reason: str
    """A sentence a reader who did not write the backend can act on."""

    @property
    def is_servable_now(self) -> bool:
        return self.state == "servable"

    @property
    def can_never_be_served(self) -> bool:
        return self.state == "unavailable"


def servable(name: str, reason: str = "") -> ObservableSupport:
    """Declare an observable this run can produce as it stands."""
    return ObservableSupport(name=name, state="servable", reason=reason or "served by this run")


def under_condition(name: str, reason: str) -> ObservableSupport:
    """Declare an observable one declaration away, naming the declaration."""
    return ObservableSupport(name=name, state="servable_under_condition", reason=reason)


def unavailable(name: str, reason: str) -> ObservableSupport:
    """Declare an observable this backend cannot produce, whatever the file says."""
    return ObservableSupport(name=name, state="unavailable", reason=reason)


__all__ = [
    "ObservableSupport",
    "State",
    "servable",
    "unavailable",
    "under_condition",
]
