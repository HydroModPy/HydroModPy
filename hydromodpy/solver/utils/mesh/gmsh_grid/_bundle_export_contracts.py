"""Internal contracts used while exporting catchment mesh bundles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GeologyFractionRow:
    """One non-zero geology fraction attached to one exported cell."""

    cell_id: int
    geology_key: str
    fraction: float

    def to_mapping(self) -> dict[str, object]:
        return {
            "cell_id": int(self.cell_id),
            "geology_key": str(self.geology_key),
            "fraction": float(self.fraction),
        }


@dataclass(frozen=True)
class GeologyProjectionPayload:
    """Resolved geology payload projected from the source support onto the mesh."""

    available: bool
    field_id: str | None = None
    zone_keys: tuple[str, ...] = ()
    cell_zone_keys: tuple[str, ...] = ()
    cell_zone_codes: tuple[int, ...] = ()
    fraction_rows: tuple[GeologyFractionRow, ...] = ()
    source_kind: str | None = None
    cell_samples_per_axis: int | None = None


@dataclass(frozen=True)
class HydraulicPropertyPayload:
    """Resolved hydraulic property mapped by geology zone and then by cell."""

    property_name: str
    available: bool
    values_by_zone_key: dict[str, float] = field(default_factory=dict)
    default_value: float | None = None
    values_source: str | None = None
    values_csv_file: str | None = None
    zone_keys_defined: tuple[str, ...] = ()
    output_field: str | None = None
    unit: str | None = None
    cell_values: tuple[float | None, ...] = ()
    missing_zone_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class HydraulicPropertiesPayload:
    """Resolved conductivity and storage payloads projected to cell values."""

    available: bool
    averaging: str
    conductivity: HydraulicPropertyPayload
    storage_coefficient: HydraulicPropertyPayload


@dataclass(frozen=True)
class CatchmentBundleMetadata:
    """Top-level metadata sidecar written next to one exported mesh bundle."""

    payload: dict[str, Any]

    def to_mapping(self) -> dict[str, Any]:
        return dict(self.payload)


__all__ = [
    "CatchmentBundleMetadata",
    "GeologyFractionRow",
    "GeologyProjectionPayload",
    "HydraulicPropertiesPayload",
    "HydraulicPropertyPayload",
]
