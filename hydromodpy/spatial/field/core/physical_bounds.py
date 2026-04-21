"""Central registry of physical bounds for HydroModPy parameters.

This table is consulted by field-level and section-level validators so that
obviously unphysical values (negative K, Sy > 1, recharge of 100 m/day...)
fail fast at config construction, before any solver call.

The registry is indexed by a normalized parameter identifier (lowercased).
Each entry states the expected canonical unit and the absolute min/max
bounds in that unit. Values are *inclusive* of both ends.

Example
-------
>>> validate_physical_value(param_id="K", value=1e-4)
1e-4
>>> validate_physical_value(param_id="K", value=1e4)  # doctest: +IGNORE_EXCEPTION_DETAIL
Traceback (most recent call last):
    ...
ValueError: hydraulic conductivity (id='K') value 10000.0 outside ...

Notes
-----
Unit coercion is performed by the caller via ``hydromodpy.core.units``;
``validate_physical_value`` only enforces numerical bounds in the canonical
unit.
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
    "k":               PhysicalBound("m/s",   1e-14, 1e2,  "hydraulic conductivity"),
    "kh":              PhysicalBound("m/s",   1e-14, 1e2,  "horizontal hydraulic conductivity"),
    "kv":              PhysicalBound("m/s",   1e-14, 1e2,  "vertical hydraulic conductivity"),
    "vka":             PhysicalBound("-",     1e-3,  1e2,  "vertical anisotropy Kv/Kh"),
    "transmissivity":  PhysicalBound("m**2/s", 1e-10, 1e3, "transmissivity"),
    "t":               PhysicalBound("m**2/s", 1e-10, 1e3, "transmissivity"),
    # ---- Storage --------------------------------------------------------
    "ss":              PhysicalBound("1/m",   1e-9,  1e-3, "specific storage"),
    "specific_storage":PhysicalBound("1/m",   1e-9,  1e-3, "specific storage"),
    "sy":              PhysicalBound("-",     1e-4,  0.5,  "specific yield"),
    "specific_yield":  PhysicalBound("-",     1e-4,  0.5,  "specific yield"),
    # ---- Porosity -------------------------------------------------------
    "n":               PhysicalBound("-",     1e-3,  0.6,  "porosity"),
    "n_eff":           PhysicalBound("-",     1e-3,  0.6,  "effective porosity"),
    "porosity":        PhysicalBound("-",     1e-3,  0.6,  "porosity"),
    # ---- Elevation / geometry ------------------------------------------
    "elevation":       PhysicalBound("m",     -500.0, 9000.0, "elevation"),
    "thickness":       PhysicalBound("m",     0.0, 10_000.0, "aquifer thickness"),
    # ---- Fluxes --------------------------------------------------------
    "recharge":        PhysicalBound("mm/day", -5000.0, 5000.0, "recharge flux"),
    # ---- Solver tolerances ---------------------------------------------
    "nwt_headtol":     PhysicalBound("m",     1e-8, 1.0,    "NWT head tolerance"),
    "nwt_fluxtol":     PhysicalBound("-",     1e-4, 1e5,    "NWT flux tolerance"),
    "mf6_outer_dvclose": PhysicalBound("m",   1e-10, 1.0,   "MF6 outer convergence dv-close"),
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
    if unit is not None and unit != bound.canonical_unit:
        raise PhysicalBoundsError(
            f"{bound.label} (id={param_id!r}) expects unit "
            f"{bound.canonical_unit!r}, got {unit!r}"
        )
    if not (bound.lo <= float(value) <= bound.hi):
        raise PhysicalBoundsError(
            f"{bound.label} (id={param_id!r}) value {value} outside "
            f"[{bound.lo}, {bound.hi}] {bound.canonical_unit}"
        )
    return float(value)


__all__ = [
    "PHYSICAL_BOUNDS",
    "PhysicalBound",
    "PhysicalBoundsError",
    "validate_physical_value",
]
