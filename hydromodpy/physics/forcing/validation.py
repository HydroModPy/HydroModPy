"""Validation helpers for numeric forcing payloads."""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real

import numpy as np

# The ceiling the soil reservoir sets on a daily rain: a recharge cannot pass it.
MAX_PLAUSIBLE_RECHARGE_MM_DAY = 1000.0


def refuse_an_impossible_recharge(peak_mm_day: float, *, label: str) -> None:
    """Refuse a recharge rate beyond any daily rainfall, the mark of a wrong unit."""
    if peak_mm_day > MAX_PLAUSIBLE_RECHARGE_MM_DAY:
        raise ValueError(
            f"{label} reaches {peak_mm_day:g} mm/day, beyond any daily rainfall: check "
            "the unit it is written in (units, or source_unit for a grid)."
        )


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


def integer_period_keys(table: Mapping[object, object], *, label: str) -> dict[int, object]:
    """Return a ``{period: rate}`` table with integer keys.

    A TOML key is always a string, so ``{"0" = 1.0}`` reaches the solvers here
    as ``{0: 1.0}``.
    """
    periods: dict[int, object] = {}
    for key, value in table.items():
        try:
            period = int(key)
            if isinstance(key, bool) or float(key) != period:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError(f"{label} key {key!r} is not a period index.") from None
        if period < 0:
            raise ValueError(f"{label} key {key!r} is not a period index: periods count from 0.")
        if period in periods:
            raise ValueError(f"{label} names period {period} twice.")
        periods[period] = value
    return periods


def complete_period_table(
    table: Mapping[object, object], *, nper: int, label: str
) -> dict[int, object]:
    """Return a ``{period: rate}`` table that states every period of the run, or refuse.

    A missing period has no rate to take: repeating the last one or reading zero
    would both change the water the model receives without saying so.
    """
    periods = integer_period_keys(table, label=label)
    expected = set(range(int(nper)))
    missing = sorted(expected - set(periods))
    if missing:
        raise ValueError(
            f"{label} gives no rate for period(s) {missing} of the {int(nper)} periods "
            "of this run: state every period, or give one number or one list."
        )
    outside = sorted(set(periods) - expected)
    if outside:
        raise ValueError(
            f"{label} names period(s) {outside}, outside the {int(nper)} periods of this run."
        )
    return {period: periods[period] for period in sorted(periods)}


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
    "MAX_PLAUSIBLE_RECHARGE_MM_DAY",
    "complete_period_table",
    "ensure_finite_numeric_payload",
    "ensure_non_negative_numeric_payload",
    "has_temporal_index",
    "integer_period_keys",
    "numeric_payload_array",
    "refuse_an_impossible_recharge",
]
