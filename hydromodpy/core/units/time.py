"""Time-unit helpers centered on SI (seconds), with the MODFLOW and pandas spellings."""

from __future__ import annotations

from hydromodpy.core.units.quantities import (
    QUANTITIES,
    factor_to_si,
    normalize_unit,
    require_number,
)

TIME_CANONICAL_UNITS: tuple[str, ...] = tuple(QUANTITIES["time"][2])

# MODFLOW ITMUNI code n is TIME_CANONICAL_UNITS[n - 1].
_PANDAS_TIMEDELTA_UNITS: dict[str, str] = {
    "seconds": "s",
    "minutes": "m",
    "hours": "h",
    "days": "d",
}


def _parse_itmuni_code(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if float(value).is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        token = value.strip()
        if token == "":
            return None
        try:
            return int(token)
        except ValueError:
            return None
    return None


def normalize_time_unit(unit: object) -> str:
    """Normalize one time unit payload to canonical plural text."""
    itmuni = _parse_itmuni_code(unit)
    if itmuni is None:
        return normalize_unit("time", unit)
    if not 1 <= itmuni <= len(TIME_CANONICAL_UNITS):
        raise ValueError(f"Unsupported ITMUNI code {itmuni!r}. Expected 1..5.")
    return TIME_CANONICAL_UNITS[itmuni - 1]


def factor_to_seconds(unit: object) -> float:
    """Return multiplicative factor to convert one unit to seconds."""
    return factor_to_si("time", normalize_time_unit(unit))


def convert_to_seconds(
    value: object,
    *,
    unit: object,
    label: str = "value",
) -> float:
    """Convert one numeric value from ``unit`` to seconds."""
    number = require_number(value, f"{label} must be numeric to convert to seconds.")
    return number * factor_to_seconds(unit)


def convert_seconds_to_unit(
    value_seconds: object,
    *,
    unit: object,
    label: str = "value_seconds",
) -> float:
    """Convert one numeric value in seconds to another time unit."""
    number = require_number(value_seconds, f"{label} must be numeric to convert from seconds.")
    return number / factor_to_seconds(unit)


def to_modflow_itmuni(unit: object) -> int:
    """Return MODFLOW ITMUNI integer code from unit payload."""
    return TIME_CANONICAL_UNITS.index(normalize_time_unit(unit)) + 1


def to_modflow6_time_units(unit: object) -> str:
    """Return MODFLOW 6 ``time_units`` text token."""
    return normalize_time_unit(unit)


def to_pandas_timedelta_unit(unit: object) -> str:
    """Return pandas ``to_timedelta`` unit alias for one canonical time unit."""
    canonical = normalize_time_unit(unit)
    alias = _PANDAS_TIMEDELTA_UNITS.get(canonical)
    if alias is None:
        raise ValueError(
            "Unsupported pandas Timedelta conversion for unit "
            f"{canonical!r}. Use seconds/minutes/hours/days."
        )
    return alias


def timedelta_to_seconds(delta: object, *, label: str = "delta") -> float:
    """Convert one timedelta-like payload to seconds."""
    if hasattr(delta, "total_seconds"):
        return float(delta.total_seconds())
    raise TypeError(f"{label} must provide a total_seconds() method.")


CF_EPOCH = "1970-01-01T00:00:00Z"
CF_TIME_UNITS = "seconds since 1970-01-01T00:00:00Z"


def cf_time_axis_seconds(relative_seconds, start_datetime: object | None):
    """Return an int64 CF time axis (seconds since the 1970 epoch).

    ``relative_seconds`` are the per-output elapsed seconds on the model clock.
    When ``start_datetime`` is given, the axis is anchored to that calendar start
    (``start + relative``); otherwise the relative seconds are kept as-is (no
    calendar anchor, reference epoch 1970). The result always has the same length
    as ``relative_seconds`` so it matches the field time axis.
    """
    import numpy as np

    relative = np.rint(np.asarray(relative_seconds, dtype=float)).astype("int64")
    if start_datetime is None:
        return relative
    import pandas as pd

    start = pd.Timestamp(start_datetime)
    start = start.tz_localize("UTC") if start.tz is None else start.tz_convert("UTC")
    start_seconds = int((start - pd.Timestamp(CF_EPOCH)).total_seconds())
    return (relative + start_seconds).astype("int64")
