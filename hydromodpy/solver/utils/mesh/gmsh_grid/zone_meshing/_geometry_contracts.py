"""Internal dataclasses shared by geometry-cleaning helpers.

The public meshing workflow mostly consumes higher-level contracts from
``contracts.py``. The helpers in this file stay intentionally small and local
to the Shapely preprocessing pipeline so that polygon cleaning, overlap
resolution and constraint splitting can share one common vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from shapely.geometry import MultiPolygon, Polygon


@dataclass(frozen=True)
class ZoneDomainCleaningDiagnostics:
    """Counters emitted while cleaning one support-domain geometry."""

    invalid_geometry_count: int = 0
    invalid_geometries_repaired_count: int = 0
    polygon_parts_before_area_filter_count: int = 0
    polygon_parts_removed_by_area_threshold_count: int = 0
    polygon_parts_kept_count: int = 0

    def to_mapping(self) -> dict[str, int]:
        """Serialize domain-cleaning diagnostics to summary-friendly keys."""
        return {
            "domain_invalid_geometry_count": int(self.invalid_geometry_count),
            "domain_invalid_geometries_repaired_count": int(
                self.invalid_geometries_repaired_count
            ),
            "domain_polygon_parts_before_area_filter_count": int(
                self.polygon_parts_before_area_filter_count
            ),
            "domain_polygon_parts_removed_by_area_threshold_count": int(
                self.polygon_parts_removed_by_area_threshold_count
            ),
            "domain_polygon_parts_kept_count": int(self.polygon_parts_kept_count),
        }


@dataclass(frozen=True)
class ZoneRowCleaningDiagnostics:
    """Counters emitted while cleaning and clipping zone-source rows."""

    source_feature_count: int = 0
    source_invalid_geometry_count: int = 0
    invalid_geometries_repaired_count: int = 0
    features_skipped_empty_zone_key_count: int = 0
    features_skipped_empty_geometry_count: int = 0
    features_outside_domain_count: int = 0
    features_after_domain_clip_count: int = 0
    features_dropped_after_cleaning_count: int = 0
    polygon_parts_before_area_filter_count: int = 0
    polygons_removed_by_area_threshold_count: int = 0
    polygon_parts_kept_count: int = 0
    cleaned_zone_polygon_count: int = 0

    def to_mapping(self) -> dict[str, int]:
        """Serialize row-cleaning diagnostics to summary-friendly keys."""
        return {
            "source_feature_count": int(self.source_feature_count),
            "source_invalid_geometry_count": int(self.source_invalid_geometry_count),
            "invalid_geometries_repaired_count": int(
                self.invalid_geometries_repaired_count
            ),
            "features_skipped_empty_zone_key_count": int(
                self.features_skipped_empty_zone_key_count
            ),
            "features_skipped_empty_geometry_count": int(
                self.features_skipped_empty_geometry_count
            ),
            "features_outside_domain_count": int(self.features_outside_domain_count),
            "features_after_domain_clip_count": int(
                self.features_after_domain_clip_count
            ),
            "features_dropped_after_cleaning_count": int(
                self.features_dropped_after_cleaning_count
            ),
            "polygon_parts_before_area_filter_count": int(
                self.polygon_parts_before_area_filter_count
            ),
            "polygons_removed_by_area_threshold_count": int(
                self.polygons_removed_by_area_threshold_count
            ),
            "polygon_parts_kept_count": int(self.polygon_parts_kept_count),
            "cleaned_zone_polygon_count": int(self.cleaned_zone_polygon_count),
        }


@dataclass(frozen=True)
class CleanedZonePolygonRow:
    """One cleaned polygon part ready for grouping and overlap resolution."""

    zone_key: str
    polygon: Polygon
    priority: float | None = None


@dataclass(frozen=True)
class ZoneGeometryGrouping:
    """Grouped per-zone geometries and priorities derived from cleaned rows."""

    geometries: dict[str, "ZoneGeometry"]
    priorities: dict[str, float] = field(default_factory=dict)


ZoneGeometry: TypeAlias = Polygon | MultiPolygon


__all__ = [
    "CleanedZonePolygonRow",
    "ZoneDomainCleaningDiagnostics",
    "ZoneGeometry",
    "ZoneGeometryGrouping",
    "ZoneRowCleaningDiagnostics",
]
