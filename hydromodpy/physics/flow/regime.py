"""Shared flow-regime vocabulary."""

from __future__ import annotations

from typing import Literal

FlowRegime = Literal["steady", "transient"]


def normalize_flow_regime(value: object) -> FlowRegime:
    """Return the canonical solver-facing flow regime."""
    text = str(value).strip().lower()
    if text == "steady" or text == "transient":
        return text
    raise ValueError("flow.flow_regime must be 'steady' or 'transient'.")


__all__ = (
    "FlowRegime",
    "normalize_flow_regime",
)
