"""Shared flow-regime vocabulary."""

from __future__ import annotations

from typing import Literal

FlowRegime = Literal["steady", "transient"]

_FLOW_REGIME_ALIASES = {
    "steady": "steady",
    "transient": "transient",
}


def normalize_flow_regime(value: object) -> FlowRegime:
    """Return the canonical solver-facing flow regime."""
    text = str(value).strip().lower()
    try:
        return _FLOW_REGIME_ALIASES[text]  # type: ignore[return-value]
    except KeyError as exc:
        raise ValueError("flow.flow_regime must be 'steady' or 'transient'.") from exc


__all__ = (
    "FlowRegime",
    "normalize_flow_regime",
)
