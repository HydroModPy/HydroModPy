"""Shared flow-regime vocabulary."""

from __future__ import annotations

from typing import Literal

FlowRegime = Literal["steady", "transient"]
FlowRegimeInput = Literal["steady", "permanent", "transient"]

_FLOW_REGIME_ALIASES: dict[str, FlowRegime] = {
    "steady": "steady",
    "permanent": "steady",
    "transient": "transient",
}


def normalize_flow_regime(value: object) -> FlowRegime:
    """Return the canonical solver-facing flow regime."""
    text = str(value).strip().lower()
    try:
        return _FLOW_REGIME_ALIASES[text]
    except KeyError as exc:
        raise ValueError("flow.flow_regime must be 'steady', 'permanent', or 'transient'.") from exc


def is_permanent_flow_regime(value: object) -> bool:
    """Return whether one regime represents a permanent/steady-state flow run."""
    return normalize_flow_regime(value) == "steady"


__all__ = (
    "FlowRegime",
    "FlowRegimeInput",
    "is_permanent_flow_regime",
    "normalize_flow_regime",
)
