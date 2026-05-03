"""Shared flow-regime vocabulary.

HydroModPy uses ``steady`` and ``transient`` as canonical solver-facing
regimes.  ``permanent`` is accepted as a user-facing hydrological alias for
``steady`` so documentation and TOML configs can use the French/field concept
without forcing every solver backend to support a third execution mode.
"""

from __future__ import annotations

from typing import Literal

FlowRegime = Literal["steady", "transient"]
FlowRegimeInput = Literal["steady", "permanent", "transient"]

_FLOW_REGIME_ALIASES = {
    "steady": "steady",
    "permanent": "steady",
    "transient": "transient",
}


def normalize_flow_regime(value: object) -> FlowRegime:
    """Return the canonical solver-facing flow regime.

    ``permanent`` is normalized to ``steady``.  This keeps the execution layer
    stable while making the permanent-flow concept explicit at the public API
    and configuration boundaries.
    """
    text = str(value).strip().lower()
    try:
        return _FLOW_REGIME_ALIASES[text]  # type: ignore[return-value]
    except KeyError as exc:
        raise ValueError(
            "flow.flow_regime must be 'steady', 'permanent', or 'transient'."
        ) from exc


def is_permanent_flow_regime(value: object) -> bool:
    """Return whether one regime represents a permanent/steady-state flow run."""
    return normalize_flow_regime(value) == "steady"


__all__ = (
    "FlowRegime",
    "FlowRegimeInput",
    "is_permanent_flow_regime",
    "normalize_flow_regime",
)
