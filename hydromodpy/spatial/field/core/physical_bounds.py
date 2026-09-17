"""Central registry of physical bounds for HydroModPy parameters.

This table is consulted by field-level and section-level validators so that
obviously unphysical values (negative K, Sy > 1, recharge of 100 m/day...)
fail fast at config construction, before any solver call.

A bound refuses what no declaration explains, which is not the same as what no
aquifer exhibits: where a value is a stated numerical device rather than a
measurement, the bound sits under physical attainability and says so on the
entry. What the table is never allowed to become is a default: a range here is a
ceiling on the bounds a calibration declares, and the span a search walks still
belongs to the file that declares it.

The registry is indexed by a normalized parameter identifier (lowercased).
Each entry states the expected canonical unit and the absolute min/max
bounds in that unit. Values are *inclusive* of both ends.

Example
-------
>>> validate_physical_value(param_id="K", value=1e-4)
0.0001
>>> validate_physical_value(
...     param_id="K", value=1e4
... )  # doctest: +IGNORE_EXCEPTION_DETAIL
Traceback (most recent call last):
    ...
PhysicalBoundsError: hydraulic conductivity (id='K') value 10000.0 outside ...

Notes
-----
A value handed in another unit of the same quantity is converted here before
the range check, so ``1e-7 m-1`` and ``1e-7 1/m`` are the same statement and a
conductivity in ``m/day`` is compared against a range written in ``m/s``. What
is refused is a unit that measures something else. That mattered little while
a bound carried the unit only when a file typed one; a calibration parameter
now inherits the unit of the field it names, so every spelling the schema
accepts reaches this comparison.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhysicalBound:
    """One physical-range entry.

    Attributes
    ----------
    canonical_unit
        The unit in which *lo* and *hi* are expressed.
    lo, hi
        Inclusive numerical bounds in ``canonical_unit``.
    label
        Human-readable name used in error messages.
    """

    canonical_unit: str
    lo: float
    hi: float
    label: str


PHYSICAL_BOUNDS: dict[str, PhysicalBound] = {
    # ---- Hydraulic parameters -------------------------------------------
    "k": PhysicalBound("m/s", 1e-14, 1e2, "hydraulic conductivity"),
    "kh": PhysicalBound("m/s", 1e-14, 1e2, "horizontal hydraulic conductivity"),
    "kv": PhysicalBound("m/s", 1e-14, 1e2, "vertical hydraulic conductivity"),
    "vka": PhysicalBound("-", 1e-3, 1e2, "vertical anisotropy Kv/Kh"),
    "transmissivity": PhysicalBound("m**2/s", 1e-10, 1e3, "transmissivity"),
    "t": PhysicalBound("m**2/s", 1e-10, 1e3, "transmissivity"),
    # ---- Storage --------------------------------------------------------
    # The floor sits three decades under any attainable specific storage. A
    # rigid matrix at the porosity floor of this very table still stores
    # rho*g*n*beta ~ 4e-9 1/m, so a tighter bound would only ever refuse a value
    # nobody measured: the declaration that confined storage is switched off and
    # the response belongs to Sy. Every unconfined 1D benchmark in
    # `validation_cases/` makes that declaration as `1e-10 m-1`, and the
    # analytical solution it is compared against carries no confined storage
    # term at all. Zero would say it plainer, but these bounds are also the span
    # a log-space search walks, and log(0) is not a number.
    "ss": PhysicalBound("1/m", 1e-12, 1e-3, "specific storage"),
    "specific_storage": PhysicalBound("1/m", 1e-12, 1e-3, "specific storage"),
    "sy": PhysicalBound("-", 1e-4, 0.5, "specific yield"),
    "specific_yield": PhysicalBound("-", 1e-4, 0.5, "specific yield"),
    # ---- Porosity -------------------------------------------------------
    "n": PhysicalBound("-", 1e-3, 0.6, "porosity"),
    "n_eff": PhysicalBound("-", 1e-3, 0.6, "effective porosity"),
    "porosity": PhysicalBound("-", 1e-3, 0.6, "porosity"),
    # ---- Elevation / geometry ------------------------------------------
    "elevation": PhysicalBound("m", -500.0, 9000.0, "elevation"),
    "thickness": PhysicalBound("m", 0.0, 10_000.0, "aquifer thickness"),
    # ---- Fluxes --------------------------------------------------------
    "recharge": PhysicalBound("mm/day", -5000.0, 5000.0, "recharge flux"),
    # ---- Solver tolerances ---------------------------------------------
    "nwt_headtol": PhysicalBound("m", 1e-8, 1.0, "NWT head tolerance"),
    "nwt_fluxtol": PhysicalBound("-", 1e-4, 1e5, "NWT flux tolerance"),
    "mf6_outer_dvclose": PhysicalBound("m", 1e-10, 1.0, "MF6 outer convergence dv-close"),
}


class PhysicalBoundsError(ValueError):
    """Raised when a numeric value breaches the central PHYSICAL_BOUNDS."""


def validate_physical_value(
    *,
    param_id: str,
    value: float,
    unit: str | None = None,
) -> float:
    """Validate *value* against the central PHYSICAL_BOUNDS registry.

    Parameters
    ----------
    param_id
        Parameter identifier (e.g. ``"K"``, ``"Sy"``). Lookup is
        case-insensitive. Unknown ids are accepted silently so that the
        registry can be extended incrementally.
    value
        Numerical value, already expressed in the canonical unit of the
        entry (the caller is responsible for unit coercion via
        ``hydromodpy.core.units``).
    unit
        If provided, must match the entry's ``canonical_unit``. The goal
        is to catch unit mismatches that would silently pass a numeric
        range check.

    Returns
    -------
    float
        The validated value (identity on success).

    Raises
    ------
    PhysicalBoundsError
        If the value is outside [lo, hi], or if *unit* does not match
        the registry's canonical unit.
    """
    bound = PHYSICAL_BOUNDS.get(param_id.lower())
    if bound is None:
        return value
    compared = float(value)
    if unit is not None:
        converted = _in_canonical_unit(compared, unit, bound.canonical_unit)
        if converted is None:
            raise PhysicalBoundsError(
                f"{bound.label} (id={param_id!r}) expects {bound.canonical_unit!r} or a unit "
                f"convertible to it, got {unit!r}"
            )
        compared = converted
    if not (bound.lo <= compared <= bound.hi):
        written = "" if compared == float(value) else f" ({compared:g} {bound.canonical_unit})"
        raise PhysicalBoundsError(
            f"{bound.label} (id={param_id!r}) value {value}{written} outside "
            f"[{bound.lo}, {bound.hi}] {bound.canonical_unit}"
        )
    return float(value)


def _in_canonical_unit(value: float, unit: str, canonical: str) -> float | None:
    """Return ``value`` expressed in ``canonical``, or None if that is not a conversion.

    Two units are the same quantity or they are not. Spelling is settled first,
    because ``1/m`` and ``m-1`` are one unit written twice and the schema and
    this registry chose different sides; a scale factor follows only where the
    quantity has one.
    """
    from hydromodpy.core.units.hydraulic_conductivity import (
        factor_to_m_per_s,
        normalize_m_per_s_unit,
    )
    from hydromodpy.core.units.length import factor_to_m, normalize_length_unit

    def spelled(token: str) -> str:
        return str(token).strip().lower().replace(" ", "").replace("**", "")

    source, target = spelled(unit), spelled(canonical)
    if source == target:
        return value

    inverse_length = {"m-1": "m", "1/m": "m", "m^-1": "m", "cm-1": "cm", "1/cm": "cm"}
    if source in inverse_length and target in inverse_length:
        # 1 cm-1 is 100 m-1: the factor of the length inverts with it.
        return value * factor_to_m(inverse_length[target]) / factor_to_m(inverse_length[source])

    for normalize, factor in (
        (normalize_m_per_s_unit, factor_to_m_per_s),
        (normalize_length_unit, factor_to_m),
    ):
        try:
            if normalize(source) == normalize(target):
                return value
            return value * factor(source) / factor(target)
        except (ValueError, KeyError):
            continue
    return None


__all__ = [
    "PHYSICAL_BOUNDS",
    "PhysicalBound",
    "PhysicalBoundsError",
    "validate_physical_value",
]
