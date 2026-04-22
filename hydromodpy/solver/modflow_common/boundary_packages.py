"""Shared descriptors for MODFLOW boundary-condition stress-period data.

MODFLOW-NWT and MODFLOW 6 both expect stress-period payloads of the
form ``(layer, row, col, *attrs)`` (DIS) or ``((layer, cell_id), *attrs)``
(DISV). The attributes depend on the package:

- ``DRN`` : ``elev, cond``
- ``GHB`` : ``bhead, cond``
- ``RIV`` : ``stage, cond, rbot``
- ``CHD`` : ``head``
- ``WEL`` : ``flux``

This module centralises the attribute names and the helper that turns a
dataclass payload into a tuple row, so that both backends share a single
source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PackageKind(str, Enum):
    """MODFLOW package families that share a (cell, *attrs) stress-period row."""

    DRN = "drn"
    GHB = "ghb"
    RIV = "riv"
    CHD = "chd"
    WEL = "wel"


# Attribute names, in the order MODFLOW expects them.
PACKAGE_ATTRS: dict[PackageKind, tuple[str, ...]] = {
    PackageKind.DRN: ("elev", "cond"),
    PackageKind.GHB: ("bhead", "cond"),
    PackageKind.RIV: ("stage", "cond", "rbot"),
    PackageKind.CHD: ("head",),
    PackageKind.WEL: ("flux",),
}


@dataclass(frozen=True)
class BoundaryCell:
    """Structured-grid cell reference ``(layer, row, col)`` plus attrs."""

    layer: int
    row: int
    col: int
    attrs: tuple[float, ...] = field(default_factory=tuple)

    def as_tuple(self) -> tuple[int, int, int, *tuple[float, ...]]:  # type: ignore[misc]
        return (int(self.layer), int(self.row), int(self.col), *self.attrs)


@dataclass(frozen=True)
class DisvBoundaryCell:
    """DISV cell reference ``((layer, cell_id), *attrs)``."""

    layer: int
    cell_id: int
    attrs: tuple[float, ...] = field(default_factory=tuple)

    def as_tuple(self) -> tuple[tuple[int, int], *tuple[float, ...]]:  # type: ignore[misc]
        return ((int(self.layer), int(self.cell_id)), *self.attrs)


def package_attr_names(kind: PackageKind | str) -> tuple[str, ...]:
    """Return the attribute names (in order) for a package kind."""
    if isinstance(kind, str):
        kind = PackageKind(kind)
    return PACKAGE_ATTRS[kind]


def validate_attrs(kind: PackageKind | str, attrs: tuple[float, ...]) -> None:
    """Raise when ``attrs`` does not match the arity expected for ``kind``."""
    expected = package_attr_names(kind)
    if len(attrs) != len(expected):
        raise ValueError(
            f"{kind} expects {len(expected)} attrs {expected}, got {len(attrs)}."
        )


__all__ = [
    "BoundaryCell",
    "DisvBoundaryCell",
    "PackageKind",
    "PACKAGE_ATTRS",
    "package_attr_names",
    "validate_attrs",
]
