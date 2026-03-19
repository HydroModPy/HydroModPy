"""Time-unit helpers centered on SI (seconds)."""

from __future__ import annotations

from numbers import Real

from hydromodpy.support.units.scalar import canonical_unit_token as _canonical_unit_token


TIME_CANONICAL_UNITS: tuple[str, ...] = (
    "seconds",
    "minutes",
    "hours",
    "days",
    "years",
)


_ITMUNI_TO_UNIT: dict[int, str] = {
    1: "seconds",
    2: "minutes",
    3: "hours",
    4: "days",
    5: "years",
}


_TIME_UNIT_ALIASES: dict[str, str] = {
    "s": "seconds",
    "sec": "seconds",
    "secs": "seconds",
    "second": "seconds",
    "seconds": "seconds",
    "m": "minutes",
    "min": "minutes",
    "mins": "minutes",
    "minute": "minutes",
    "minutes": "minutes",
    "h": "hours",
    "hr": "hours",
    "hrs": "hours",
    "hour": "hours",
    "hours": "hours",
    "d": "days",
    "day": "days",
    "days": "days",
    "y": "years",
    "yr": "years",
    "yrs": "years",
    "year": "years",
    "years": "years",
}


_SECONDS_PER_UNIT: dict[str, float] = {
    "seconds": 1.0,
    "minutes": 60.0,
    "hours": 3600.0,
    "days": 86400.0,
    # Calendar-dependent by definition; this scalar is only a conventional conversion.
    "years": 365.25 * 86400.0,
}


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
    if itmuni is not None:
        canonical = _ITMUNI_TO_UNIT.get(int(itmuni))
        if canonical is not None:
            return canonical
        raise ValueError(f"Unsupported ITMUNI code {itmuni!r}. Expected 1..5.")

    token = _canonical_unit_token(str(unit))
    if token == "":
        raise ValueError("Time unit cannot be empty.")
    canonical = _TIME_UNIT_ALIASES.get(token)
    if canonical is None:
        allowed = ", ".join(TIME_CANONICAL_UNITS)
        raise ValueError(f"Unsupported time unit {unit!r}. Allowed units: {allowed}")
    return canonical


def factor_to_seconds(unit: object) -> float:
    """Return multiplicative factor to convert one unit to seconds."""
    canonical = normalize_time_unit(unit)
    return float(_SECONDS_PER_UNIT[canonical])


def convert_to_seconds(
    value: object,
    *,
    unit: object,
    label: str = "value",
) -> float:
    """Convert one numeric value from ``unit`` to seconds."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{label} must be numeric to convert to seconds.")
    return float(value) * factor_to_seconds(unit)


def convert_seconds_to_unit(
    value_seconds: object,
    *,
    unit: object,
    label: str = "value_seconds",
) -> float:
    """Convert one numeric value in seconds to another time unit."""
    if isinstance(value_seconds, bool) or not isinstance(value_seconds, Real):
        raise TypeError(f"{label} must be numeric to convert from seconds.")
    return float(value_seconds) / factor_to_seconds(unit)


def to_modflow_itmuni(unit: object) -> int:
    """Return MODFLOW ITMUNI integer code from unit payload."""
    canonical = normalize_time_unit(unit)
    reverse_map = {
        "seconds": 1,
        "minutes": 2,
        "hours": 3,
        "days": 4,
        "years": 5,
    }
    return int(reverse_map[canonical])


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
