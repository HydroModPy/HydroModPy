"""Canonical translation of HydroModPy BC kinds to MODFLOW packages.

Both MODFLOW-NWT and MODFLOW 6 translators resolve the same semantic
boundary conditions ("stream", "drain", "chd", "well", "ghb", "riv",
"ocean") to solver-specific packages. The names of the canonical BC
tokens live here so that downstream mappings stay consistent.

The module provides:

- ``BoundaryKind`` : enum of BC kinds recognised by HydroModPy.
- ``NWT_PACKAGES`` / ``MF6_PACKAGES`` : dispatch tables mapping each
  ``BoundaryKind`` to the solver package code expected by FloPy.
- ``resolve_packages`` : helper returning the package list used by an
  adapter for a given ``(BoundaryKind, solver)`` combination.

Only the naming dispatch is centralised; the detailed payload builders
stay with each backend because they depend on solver-specific data
structures (DIS vs DISV coordinates, stress period data layouts, etc.).
"""

from __future__ import annotations

from enum import StrEnum


class BoundaryKind(StrEnum):
    """Semantic boundary-condition kinds understood by HydroModPy."""

    STREAM = "stream"  # river / open channel
    DRAIN = "drain"  # drain (top-of-grid seepage)
    CHD = "chd"  # constant head
    WELL = "well"  # pumping / injection
    GHB = "ghb"  # general-head boundary
    RIV = "riv"  # river package (explicit)
    OCEAN = "ocean"  # seaward boundary (mapped to CHD/GHB)
    RECHARGE = "recharge"  # areal recharge
    EVT = "evt"  # evapotranspiration


# Dispatch tables. Values are FloPy package class suffixes ("Riv", "Drn",
# etc.) expected by the MODFLOW-NWT flopy.modflow and MODFLOW 6
# flopy.mf6 APIs.
NWT_PACKAGES: dict[BoundaryKind, str] = {
    BoundaryKind.STREAM: "Riv",
    BoundaryKind.DRAIN: "Drn",
    BoundaryKind.CHD: "Chd",
    BoundaryKind.WELL: "Wel",
    BoundaryKind.GHB: "Ghb",
    BoundaryKind.RIV: "Riv",
    BoundaryKind.OCEAN: "Chd",
    BoundaryKind.RECHARGE: "Rch",
    BoundaryKind.EVT: "Evt",
}

MF6_PACKAGES: dict[BoundaryKind, str] = {
    BoundaryKind.STREAM: "Riv",
    BoundaryKind.DRAIN: "Drn",
    BoundaryKind.CHD: "Chd",
    BoundaryKind.WELL: "Wel",
    BoundaryKind.GHB: "Ghb",
    BoundaryKind.RIV: "Riv",
    BoundaryKind.OCEAN: "Chd",
    BoundaryKind.RECHARGE: "Rcha",
    BoundaryKind.EVT: "Evta",
}


def resolve_package(kind: BoundaryKind | str, *, solver: str) -> str:
    """Return the FloPy package suffix for one ``(kind, solver)`` pair."""
    if isinstance(kind, str):
        kind = BoundaryKind(kind)
    if solver in ("modflownwt", "modflow-nwt", "nwt"):
        table = NWT_PACKAGES
    elif solver in ("modflow6", "mf6"):
        table = MF6_PACKAGES
    else:
        raise ValueError(f"Unknown MODFLOW solver key: {solver!r}")
    return table[kind]


def resolve_packages(
    kinds: list[BoundaryKind | str],
    *,
    solver: str,
) -> list[str]:
    """Return the deduplicated list of packages matching *kinds*."""
    seen: list[str] = []
    for kind in kinds:
        pkg = resolve_package(kind, solver=solver)
        if pkg not in seen:
            seen.append(pkg)
    return seen


__all__ = [
    "BoundaryKind",
    "MF6_PACKAGES",
    "NWT_PACKAGES",
    "resolve_package",
    "resolve_packages",
]
