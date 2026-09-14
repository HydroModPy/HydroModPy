"""Time-unit and rate-payload scaling helpers for MODFLOW-NWT."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

# Map MODFLOW ITMUNI codes to seconds per time unit.
# Used to convert FieldParam SI values (m/s) to solver time units.
ITMUNI_TO_SECONDS: dict[int, float] = {
    0: 1.0,  # undefined treated as seconds
    1: 1.0,  # seconds
    2: 60.0,  # minutes
    3: 3600.0,  # hours
    4: 86400.0,  # days
    5: 31557600.0,  # years (365.25 days)
}


def scale_rate_payload(payload: object, factor: float) -> object:
    """Scale a recharge / EVT rate payload by ``factor``.

    Handles the three shapes produced by ``flow_to_modflow_adapter``:
    a scalar (steady-state), a 2D ndarray (one map for the whole run),
    or a ``{kper: scalar | ndarray}`` mapping (one entry per stress
    period). Returns ``None`` unchanged so the caller can keep its
    existing skip logic.
    """
    if payload is None:
        return None
    if isinstance(payload, Mapping):
        return {kper: scale_rate_payload(value, factor) for kper, value in payload.items()}
    if isinstance(payload, np.ndarray):
        return payload * factor
    return float(payload) * factor


__all__ = ["ITMUNI_TO_SECONDS", "scale_rate_payload"]
