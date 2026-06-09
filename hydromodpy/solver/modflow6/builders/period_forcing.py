"""Shared per-period forcing helpers for MF6 advanced packages (LAK, SFR).

A boundary forcing is either a constant (one inline PERIOD row), an inline
per-period expansion (one row whenever the value changes) or an external TS6
series. These helpers hold the package-agnostic pieces of that decision: value
coercion to SI, the TS6-vs-inline arbitration and the TS6 time axis. The
package-specific row emission (lake managed-transfer neutralization, SFR
per-reach scaling) stays in each builder.
"""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real

import numpy as np

from hydromodpy.core.units.hydraulic_conductivity import parse_to_m_per_s
from hydromodpy.core.units.volumetric_flow import parse_to_m3_per_s


def _attr(payload: object, name: str) -> object:
    """Read one field from a mapping or attribute-style payload."""
    if isinstance(payload, Mapping):
        return payload.get(name)
    return getattr(payload, name, None)


def forcing_kind(forcing: object) -> str | None:
    """Return the forcing discriminator (``constant`` / ``csv`` / ...) or None."""
    kind = _attr(forcing, "kind")
    if kind is None:
        kind = _attr(forcing, "mode")
    return str(kind) if kind is not None else None


def forcing_unit(forcing: object) -> str | None:
    """Return the declared unit of one forcing payload, or None."""
    unit = _attr(forcing, "units")
    if unit is None:
        unit = _attr(forcing, "unit")
    return str(unit) if unit is not None else None


def constant_forcing_value(forcing: object) -> object:
    """Return the scalar value of a constant forcing, or None.

    A forcing may be a bare number, a ``{value, units}`` mapping, or a
    ``FlowWellForcingConstantConfig``-style object (``kind == 'constant'``). CSV /
    TS6 forcings are resolved at runtime and skipped here.
    """
    if forcing is None:
        return None
    if isinstance(forcing, Real) and not isinstance(forcing, bool):
        return float(forcing)
    kind = _attr(forcing, "kind")
    if kind is not None and str(kind) != "constant":
        return None
    value = _attr(forcing, "value")
    if value is not None:
        magnitude = getattr(value, "magnitude", value)
        return magnitude
    if isinstance(forcing, Mapping) and "value" not in forcing:
        return None
    return forcing


def forcing_to_si(
    value: object,
    forcing: object,
    location: str,
    volumetric: bool,
    *,
    explicit_unit: str | None = None,
) -> float:
    """Convert one forcing value to its canonical SI unit (m/s or m3/s)."""
    unit = explicit_unit if explicit_unit is not None else forcing_unit(forcing)
    if volumetric:
        return parse_to_m3_per_s(value, location=location, default_unit="m3/s", explicit_unit=unit)[
            0
        ]
    return parse_to_m_per_s(value, location=location, default_unit="m/s", explicit_unit=unit)[0]


def resolve_forcing_mode(model) -> tuple[str, int]:
    """Return the ``(lak_forcing_mode, ts6_min_periods)`` config pair.

    The knob is named after LAK historically but governs every advanced-package
    forcing (LAK and SFR share the TS6-vs-inline arbitration).
    """
    config = getattr(model, "modflow_config", None)
    process_specific = getattr(config, "process_specific", None)
    mode = str(getattr(process_specific, "lak_forcing_mode", "auto") or "auto")
    min_periods = int(getattr(process_specific, "ts6_min_periods", 120) or 120)
    return mode, min_periods


def resolve_use_ts6(forcing: object, *, mode: str, nper: int, min_periods: int) -> bool:
    """Return whether one forcing should be written as an external TS6 series.

    A bare-constant forcing always stays inline (a one-row TS6 file would be
    wasteful and would perturb output), so ``False`` for it regardless of mode.
    ``inline`` never uses TS6. ``ts6`` always routes a non-constant forcing.
    ``auto`` routes a non-constant forcing only when ``nper > min_periods``.
    """
    if constant_forcing_value(forcing) is not None:
        return False
    if forcing_kind(forcing) == "constant":
        return False
    if nper <= 1:
        return False
    if mode == "inline":
        return False
    if mode == "ts6":
        return True
    return nper > int(min_periods)


def package_unit_conversions(model) -> tuple[float, float]:
    """Return ``(time_conversion, length_conversion)`` for Manning-type scaling.

    MF6 LAK / SFR need these only to scale MANNING / WEIR flow formulas into the
    model's unit system. HMP runs TDIS in seconds and METERS, so both are 1.0; we
    read ``model.time_units`` to stay correct if that ever changes.
    """
    time_units = str(getattr(model, "time_units", "seconds") or "seconds").lower()
    seconds_per_unit = {
        "seconds": 1.0,
        "minutes": 60.0,
        "hours": 3600.0,
        "days": 86400.0,
        "years": 31557600.0,
    }
    return float(seconds_per_unit.get(time_units, 1.0)), 1.0


def ts6_times_and_values(
    model, per_period_si: tuple[float, ...]
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Return the TS6 ``(times, values)`` covering the whole simulation.

    Period starts are ``[0, *cumsum(perlen)[:-1]]`` so each STEPWISE breakpoint is
    the exact start of its stress period and the value is held constant over that
    period. A terminal breakpoint at the simulation end (``cumsum(perlen)[-1]``)
    repeating the last value closes the final interval, which MF6 requires to
    integrate the series over the last period.
    """
    perlen = np.asarray(model.perlen, dtype=float).ravel()
    cumulative = np.cumsum(perlen)
    starts = np.concatenate(([0.0], cumulative[:-1]))
    times = tuple(float(t) for t in starts) + (float(cumulative[-1]),)
    values = tuple(per_period_si) + (float(per_period_si[-1]),)
    return times, values


__all__ = [
    "constant_forcing_value",
    "forcing_kind",
    "forcing_to_si",
    "forcing_unit",
    "package_unit_conversions",
    "resolve_forcing_mode",
    "resolve_use_ts6",
    "ts6_times_and_values",
]
