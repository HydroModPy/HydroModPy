"""Time-discretization descriptors used by the Boussinesq solver."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimeSchemeSpec:
    """Descriptor for one time-discretization family."""

    id: str
    regime: str
    problem_kind: str
    description: str


STEADY_BALANCE = TimeSchemeSpec(
    id="steady_balance",
    regime="steady",
    problem_kind="steady_head_balance",
    description="Stationary nonlinear balance with no storage term.",
)

BACKWARD_EULER = TimeSchemeSpec(
    id="backward_euler",
    regime="transient",
    problem_kind="transient_head_balance",
    description="Fully implicit backward-Euler step on the head balance.",
)


def resolve_time_scheme(flow_regime: str | None) -> TimeSchemeSpec:
    """Return the canonical time-discretization descriptor for one regime."""

    regime = str(flow_regime or "transient").strip().lower() or "transient"
    if regime == "steady":
        return STEADY_BALANCE
    if regime == "transient":
        return BACKWARD_EULER
    raise ValueError(
        "Unsupported Boussinesq flow regime. Expected one of: steady, transient."
    )


__all__ = [
    "BACKWARD_EULER",
    "STEADY_BALANCE",
    "TimeSchemeSpec",
    "resolve_time_scheme",
]
