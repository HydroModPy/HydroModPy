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
from typing import Any

import numpy as np

from hydromodpy.core.exceptions import ConfigValidationError


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
    "k22": PhysicalBound("m/s", 1e-14, 1e2, "hydraulic conductivity along the second axis"),
    # The three angles of the K tensor, in degrees, as MODFLOW 6 NPF reads them.
    # angle1 turns the first axis from east towards north, so it is not a compass
    # azimuth (N30E is angle1 = 60). angle2 raises that axis above the horizontal.
    # A rise past the vertical is the same tensor turned by angle1, so angle2 stays
    # within a quarter turn.
    "angle1": PhysicalBound(
        "-", -360.0, 360.0, "turn of the first K axis from east towards north in degrees"
    ),
    "angle2": PhysicalBound(
        "-", -90.0, 90.0, "rise of the first K axis above the horizontal in degrees"
    ),
    "angle3": PhysicalBound("-", -360.0, 360.0, "rotation of the K tensor in degrees"),
    "transmissivity": PhysicalBound("m**2/s", 1e-10, 1e3, "transmissivity"),
    "t": PhysicalBound("m**2/s", 1e-10, 1e3, "transmissivity"),
    # ---- Exchange with lakes, streams and barriers -------------------------
    # Zero is a sealed bed or wall, which the fields accept. A leakance is
    # K_bed / thickness_bed, so the ceiling is the conductivity ceiling over a
    # centimeter of bed.
    "streambed_k": PhysicalBound("m/s", 0.0, 1e2, "streambed hydraulic conductivity"),
    "bedleak": PhysicalBound("1/s", 0.0, 1e4, "lake-bed leakance"),
    "hydchr": PhysicalBound("1/s", 0.0, 1e4, "barrier hydraulic characteristic"),
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
    # ---- Soil reservoir ---
    "soil_ru": PhysicalBound("mm", 0.0, 1000.0, "soil available water capacity"),
    "soil_alpha": PhysicalBound("-", 0.01, 1.0, "share of ru below which ETR falls"),
    "soil_kc": PhysicalBound("-", 0.0, 2.0, "crop coefficient"),
    "soil_bypass_fraction": PhysicalBound(
        "-", 0.0, 0.99, "share of the rain that bypasses the soil"
    ),
    "soil_transit_time": PhysicalBound("day", 0.0, 30.0, "transit time below the soil"),
    # The ceiling is strictly below 1 to match SoilReservoirConfig.impervious_fraction's
    # own field validator, which refuses 1 or more: a bound touching 1 would load
    # without error but fail as soon as a sampler actually draws that edge value.
    "soil_impervious_fraction": PhysicalBound("-", 0.0, 0.95, "sealed share of the area"),
    "soil_curve_number": PhysicalBound("-", 30.0, 98.0, "soil curve number (AMC II)"),
    "soil_runoff_time": PhysicalBound("day", 0.0, 10.0, "curve-number runoff routing time"),
    "soil_runoff_lag": PhysicalBound(
        "day", 0.0, 5.0, "pure delay of the routed curve-number runoff"
    ),
    # ---- EVT ---
    # The floor is strictly positive to match FlowEtpConfig.extinction_depth's
    # own `gt=0.0` constraint: a bound touching 0 would load without error but
    # fail as soon as a sampler (grid, LHS) actually draws that edge value.
    "extinction_depth": PhysicalBound("m", 1e-3, 100.0, "EVT extinction depth"),
    # ---- Vertical profile -----------------------------------------------
    # The floor keeps the exponential decay length away from zero, where it
    # would degenerate into a step function and a log-space sampler would
    # divide by it. The ceiling is past any catchment depth this project models.
    "characteristic_depth": PhysicalBound(
        "m", 0.1, 1000.0, "vertical profile characteristic depth"
    ),
    # The floor is strictly positive: a sampler drawing exactly 0 would make
    # the floor indistinguishable from "no floor" (mode='none' already says that).
    "min_factor": PhysicalBound("-", 1e-6, 1.0, "vertical profile floor factor"),
    # ---- Solver tolerances ---------------------------------------------
    "nwt_headtol": PhysicalBound("m", 1e-8, 1.0, "NWT head tolerance"),
    "nwt_fluxtol": PhysicalBound("-", 1e-4, 1e5, "NWT flux tolerance"),
    "mf6_outer_dvclose": PhysicalBound("m", 1e-10, 1.0, "MF6 outer convergence dv-close"),
}


class PhysicalBoundsError(ConfigValidationError, ValueError):
    """A value lies outside the physical range of its parameter.

    ``param_id`` is the registry id the value was checked under, or None when
    the raiser did not state one. A calibration trial reads it to tell a point
    the search moved out of range from a fixed value that is out of range.
    """

    def __init__(self, message: str = "", *, param_id: str | None = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.param_id = param_id


def validate_physical_value(
    *,
    param_id: str,
    value: float,
    unit: str | None = None,
    where: str | None = None,
) -> float:
    """Validate *value* against the central PHYSICAL_BOUNDS registry.

    Parameters
    ----------
    param_id
        Parameter identifier (e.g. ``"K"``, ``"Sy"``). Lookup is
        case-insensitive. Unknown ids are accepted silently so that the
        registry can be extended incrementally.
    value
        Numerical value, in ``unit``.
    unit
        The unit the value is written in. It is converted to the entry's
        ``canonical_unit`` before the range check, and a unit of another
        quantity is refused. None means the value is already in the
        canonical unit.
    where
        Where the value sits, such as ``"zone 'granite'"``. The refusal
        names it.

    Returns
    -------
    float
        The validated value (identity on success).

    Raises
    ------
    PhysicalBoundsError
        If the value is outside [lo, hi], or if *unit* does not convert to
        the registry's canonical unit.
    """
    bound = PHYSICAL_BOUNDS.get(param_id.lower())
    if bound is None:
        return value
    compared = float(value)
    if unit is not None:
        converted = _in_canonical_unit(compared, unit, bound.canonical_unit)
        if converted is None:
            raise _unit_refusal(bound, param_id, unit, where)
        compared = converted
    if not (bound.lo <= compared <= bound.hi):
        raise PhysicalBoundsError(
            f"{_subject(bound, param_id, where)} value {_written(float(value), unit, bound)} "
            f"outside [{bound.lo}, {bound.hi}] {bound.canonical_unit}",
            param_id=param_id,
        )
    return float(value)


def validate_physical_array(
    *,
    param_id: str,
    values: object,
    unit: str | None = None,
    where: str | None = None,
    mask: object | None = None,
) -> np.ndarray:
    """Validate every entry of *values* against the range of *param_id*.

    The array form of :func:`validate_physical_value`, for one value per cell.
    A value that is not a number is outside the range. ``mask``, of the shape
    of *values*, leaves out the entries where it is False. The refusal counts
    the values outside and names the first one by its flat index.
    """
    array = np.asarray(values, dtype=float)
    bound = PHYSICAL_BOUNDS.get(param_id.lower())
    if bound is None:
        return array
    compared = array * _canonical_factor(bound, param_id=param_id, unit=unit, where=where)
    outside = ~((compared >= bound.lo) & (compared <= bound.hi))
    if mask is not None:
        outside &= np.asarray(mask, dtype=bool)
    count = int(np.count_nonzero(outside))
    if count:
        first = int(np.flatnonzero(outside)[0])
        raise PhysicalBoundsError(
            f"{_subject(bound, param_id, where)}: {count} of {array.size} value(s) outside "
            f"[{bound.lo}, {bound.hi}] {bound.canonical_unit}, the first at index {first}: "
            f"{_written(float(array.flat[first]), unit, bound)}",
            param_id=param_id,
        )
    return array


def _subject(bound: PhysicalBound, param_id: str, where: str | None) -> str:
    """The parameter a refusal is about, and where its value sits."""
    place = "" if where is None else f" in {where}"
    return f"{bound.label} (id={param_id!r}){place}"


def _written(value: float, unit: str | None, bound: PhysicalBound) -> str:
    """A value in the unit it was declared in, then in the canonical unit."""
    if unit is None:
        return f"{value}"
    canonical = _in_canonical_unit(value, unit, bound.canonical_unit)
    if canonical is None or canonical == value:
        return f"{value} {unit}"
    return f"{value} {unit} ({canonical:g} {bound.canonical_unit})"


def _canonical_factor(
    bound: PhysicalBound, *, param_id: str, unit: str | None, where: str | None
) -> float:
    """The factor that takes a value in ``unit`` to the canonical unit of ``bound``.

    Every unit of the registry is a plain scale of its canonical unit, with no
    offset, so one factor converts a whole array.
    """
    if unit is None:
        return 1.0
    factor = _in_canonical_unit(1.0, unit, bound.canonical_unit)
    if factor is None:
        raise _unit_refusal(bound, param_id, unit, where)
    return factor


def _unit_refusal(
    bound: PhysicalBound, param_id: str, unit: str, where: str | None
) -> PhysicalBoundsError:
    """The refusal of a unit that measures another quantity."""
    return PhysicalBoundsError(
        f"{_subject(bound, param_id, where)} expects {bound.canonical_unit!r} or a unit "
        f"convertible to it, got {unit!r}",
        param_id=param_id,
    )


def _in_canonical_unit(value: float, unit: str, canonical: str) -> float | None:
    """Return ``value`` expressed in ``canonical``, or None if that is not a conversion.

    Two units are the same quantity or they are not. ``1/m`` and ``m-1`` are one
    unit written twice, and the schema and this registry chose different sides.
    """
    from hydromodpy.core.units.parse import convert_between_units

    try:
        return convert_between_units(value, from_unit=unit, to_unit=canonical)
    except ValueError:
        return None


__all__ = [
    "PHYSICAL_BOUNDS",
    "PhysicalBound",
    "PhysicalBoundsError",
    "validate_physical_array",
    "validate_physical_value",
]
