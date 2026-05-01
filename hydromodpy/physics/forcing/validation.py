"""Validation helpers for numeric forcing payloads."""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real

import numpy as np


def has_temporal_index(payload: object) -> bool:
    """Return True when a payload index carries datetime-like labels."""
    index = getattr(payload, "index", None)
    if index is None:
        return False
    try:
        import pandas as pd
    except Exception:
        return False
    if isinstance(index, pd.DatetimeIndex):
        return True
    inferred_type = str(getattr(index, "inferred_type", "") or "")
    if inferred_type in {"integer", "mixed-integer", "floating"}:
        return False
    try:
        converted = pd.to_datetime(index, errors="coerce")
    except Exception:
        return False
    if isinstance(converted, pd.Timestamp):
        return not bool(pd.isna(converted))
    try:
        length = len(converted)
    except TypeError:
        return not bool(pd.isna(converted))
    return bool(length > 0 and not converted.isna().any())


def numeric_payload_array(payload: object, *, label: str) -> np.ndarray:
    """Return one finite numeric payload as a flat array."""
    if payload is None:
        raise ValueError(f"{label} cannot be None.")
    if isinstance(payload, bool):
        raise TypeError(f"{label} must be numeric.")
    if isinstance(payload, Real):
        array = np.asarray([float(payload)], dtype=float)
    elif hasattr(payload, "to_numpy"):
        array = np.asarray(payload.to_numpy(), dtype=float).reshape(-1)
    elif hasattr(payload, "iloc"):
        array = np.asarray([payload.iloc[idx] for idx in range(len(payload))], dtype=float)
    else:
        try:
            array = np.asarray(payload, dtype=float).reshape(-1)
        except Exception as exc:
            raise TypeError(f"{label} must be numeric or a numeric sequence.") from exc
    if array.size == 0:
        raise ValueError(f"{label} cannot be empty.")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{label} must contain only finite numeric values.")
    return array.astype(float, copy=False)


def ensure_finite_numeric_payload(payload: object, *, label: str) -> None:
    """Raise when one payload contains non-finite or non-numeric values."""
    if isinstance(payload, Mapping):
        if len(payload) == 0:
            raise ValueError(f"{label} mapping cannot be empty.")
        for key, value in payload.items():
            ensure_finite_numeric_payload(value, label=f"{label}[{key!r}]")
        return
    numeric_payload_array(payload, label=label)


def ensure_non_negative_numeric_payload(payload: object, *, label: str) -> None:
    """Raise when one numeric payload is non-finite or negative."""
    if isinstance(payload, Mapping):
        if len(payload) == 0:
            raise ValueError(f"{label} mapping cannot be empty.")
        for key, value in payload.items():
            ensure_non_negative_numeric_payload(value, label=f"{label}[{key!r}]")
        return
    array = numeric_payload_array(payload, label=label)
    if np.any(array < 0.0):
        raise ValueError(f"{label} must be non-negative.")


__all__ = [
    "ensure_finite_numeric_payload",
    "ensure_non_negative_numeric_payload",
    "has_temporal_index",
    "numeric_payload_array",
]
