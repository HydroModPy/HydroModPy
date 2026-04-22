"""Pint unit registry for HydroModPy.

Central pint ``UnitRegistry`` instance configured with the units commonly used
in hydrogeological modelling (lengths, hydraulic conductivities, flow rates,
dimensionless storativities, temperatures, viscosities, ...).

The registry is created lazily and shared across the package so that
``Quantity`` objects remain comparable (pint requires a single registry for
equality and arithmetic).

Canonical SI conventions used in HydroModPy
-------------------------------------------
- length:                  metre         (``m``)
- area:                    square metre  (``m**2``)
- volume:                  cubic metre   (``m**3``)
- time:                    second        (``s``)
- velocity / conductivity: metre/second  (``m/s``)
- flow rate:               m**3/s
- mass flux:               kg/s
- temperature:             degC
- pressure / viscosity:    Pa, Pa*s
- dimensionless:           ``dimensionless`` (``-``)

The registry is intentionally process-wide. Use :func:`get_registry` to access
it (creation is thread-safe via pint's own lock).
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pint import UnitRegistry


@lru_cache(maxsize=1)
def get_registry() -> UnitRegistry:
    """Return the shared pint :class:`UnitRegistry`.

    The registry is instantiated on first call and cached for the lifetime of
    the interpreter. All HydroModPy code MUST use this function (or the
    re-exports from :mod:`hydromodpy.core.units`) to obtain a registry — mixing
    registries causes pint to raise ``DimensionalityError`` on equality.
    """
    import pint

    reg = pint.UnitRegistry()

    # Aliases/extra definitions. Pint already knows most SI units; we enrich
    # it with convenient aliases for hydrogeology.
    reg.define("percent = 1e-2 = %")
    reg.define("permille = 1e-3")
    # Some datasets use "day" abbreviated as "d" — pint supports ``day`` but
    # mixed "d" occurs in legacy configs. Register as alias where safe.
    # NOTE: do not alias "d" to day — pint already uses "d" for day.

    # Default application-level formatting. Prefer ``formatter.default_format``
    # (introduced in pint >= 0.24); fall back to the deprecated attribute for
    # older pint versions.
    try:
        reg.formatter.default_format = "~P"  # compact pretty format (e.g. "m/s")
    except AttributeError:
        reg.default_format = "~P"

    return reg


# Convenience accessor: an application-level singleton. Keep in sync with the
# cached registry from get_registry().
UREG = get_registry()


__all__ = ["get_registry", "UREG"]
