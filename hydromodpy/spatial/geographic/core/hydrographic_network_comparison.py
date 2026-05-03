"""Geometric comparison helpers for canonical hydrographic networks.

This module compares two line networks on a projected support and exposes:

- length-based summary metrics,
- tolerance-based matched / missing / extra segments,
- a lightweight payload directly reusable by display figures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HydrographicNetwork,
    measure_linework_length_m,
    project_gdf_for_metric_operations,
)

if TYPE_CHECKING:
    from geopandas import GeoDataFrame


@dataclass(frozen=True)
class HydrographicNetworkComparison:
    """Tolerance-based geometric comparison between two hydrographic networks."""

    tolerance_m: float
    crs: str | None
    reference_gdf: GeoDataFrame
    candidate_gdf: GeoDataFrame
    reference_matched_gdf: GeoDataFrame
    reference_missing_gdf: GeoDataFrame
    candidate_matched_gdf: GeoDataFrame
    candidate_extra_gdf: GeoDataFrame
    reference_total_length_m: float
    candidate_total_length_m: float
    matched_reference_length_m: float
    matched_candidate_length_m: float
    missing_reference_length_m: float
    extra_candidate_length_m: float
    reference_coverage_ratio: float | None
    candidate_match_ratio: float | None
    missing_reference_ratio: float | None
    extra_candidate_ratio: float | None
    length_balance_ratio: float | None
    length_f1_ratio: float | None
    hausdorff_distance_m: float | None

    def to_metrics_record(self, **metadata: object) -> dict[str, object]:
        """Return one flat metrics payload suitable for CSV/JSON exports."""
        return {
            **metadata,
            "tolerance_m": self.tolerance_m,
            "crs": self.crs,
            "reference_segment_count": int(len(self.reference_gdf.index)),
            "candidate_segment_count": int(len(self.candidate_gdf.index)),
            "reference_matched_segment_count": int(len(self.reference_matched_gdf.index)),
            "reference_missing_segment_count": int(len(self.reference_missing_gdf.index)),
            "candidate_matched_segment_count": int(len(self.candidate_matched_gdf.index)),
            "candidate_extra_segment_count": int(len(self.candidate_extra_gdf.index)),
            "reference_total_length_m": self.reference_total_length_m,
            "candidate_total_length_m": self.candidate_total_length_m,
            "matched_reference_length_m": self.matched_reference_length_m,
            "matched_candidate_length_m": self.matched_candidate_length_m,
            "missing_reference_length_m": self.missing_reference_length_m,
            "extra_candidate_length_m": self.extra_candidate_length_m,
            "reference_coverage_ratio": self.reference_coverage_ratio,
            "candidate_match_ratio": self.candidate_match_ratio,
            "missing_reference_ratio": self.missing_reference_ratio,
            "extra_candidate_ratio": self.extra_candidate_ratio,
            "length_balance_ratio": self.length_balance_ratio,
            "length_f1_ratio": self.length_f1_ratio,
            "hausdorff_distance_m": self.hausdorff_distance_m,
        }


def compare_hydrographic_networks(
    reference: HydrographicNetwork | GeoDataFrame,
    candidate: HydrographicNetwork | GeoDataFrame,
    *,
    tolerance_m: float = 50.0,
) -> HydrographicNetworkComparison:
    """Compare two line networks using one tolerance buffer in metres."""
    import numpy as np
    from shapely.ops import unary_union

    if tolerance_m < 0:
        raise ValueError("tolerance_m must be >= 0.")

    reference_gdf = _normalize_linework(_coerce_network_gdf(reference))
    candidate_gdf = _normalize_linework(_coerce_network_gdf(candidate))

    reference_gdf = project_gdf_for_metric_operations(reference_gdf)
    reference_crs = None if reference_gdf.crs is None else str(reference_gdf.crs)
    candidate_gdf = project_gdf_for_metric_operations(
        candidate_gdf,
        fallback_crs=reference_crs,
    )
    if reference_gdf.crs is not None and candidate_gdf.crs is not None:
        if str(reference_gdf.crs) != str(candidate_gdf.crs):
            candidate_gdf = candidate_gdf.to_crs(reference_gdf.crs)
    crs = (
        str(reference_gdf.crs)
        if reference_gdf.crs is not None
        else (None if candidate_gdf.crs is None else str(candidate_gdf.crs))
    )

    reference_total_length_m = _network_length(reference_gdf)
    candidate_total_length_m = _network_length(candidate_gdf)

    reference_union = unary_union(list(reference_gdf.geometry)) if not reference_gdf.empty else None
    candidate_union = unary_union(list(candidate_gdf.geometry)) if not candidate_gdf.empty else None

    reference_buffer = (
        None
        if reference_union is None or reference_union.is_empty
        else (
            reference_union
            if float(tolerance_m) == 0.0
            else reference_union.buffer(float(tolerance_m))
        )
    )
    candidate_buffer = (
        None
        if candidate_union is None or candidate_union.is_empty
        else (
            candidate_union
            if float(tolerance_m) == 0.0
            else candidate_union.buffer(float(tolerance_m))
        )
    )

    reference_matched_gdf = _line_boolean(reference_gdf, candidate_buffer, mode="intersection")
    reference_missing_gdf = _line_boolean(reference_gdf, candidate_buffer, mode="difference")
    candidate_matched_gdf = _line_boolean(candidate_gdf, reference_buffer, mode="intersection")
    candidate_extra_gdf = _line_boolean(candidate_gdf, reference_buffer, mode="difference")

    matched_reference_length_m = _network_length(reference_matched_gdf)
    matched_candidate_length_m = _network_length(candidate_matched_gdf)
    missing_reference_length_m = _network_length(reference_missing_gdf)
    extra_candidate_length_m = _network_length(candidate_extra_gdf)

    reference_coverage_ratio = _safe_ratio(matched_reference_length_m, reference_total_length_m)
    candidate_match_ratio = _safe_ratio(matched_candidate_length_m, candidate_total_length_m)
    missing_reference_ratio = _safe_ratio(missing_reference_length_m, reference_total_length_m)
    extra_candidate_ratio = _safe_ratio(extra_candidate_length_m, candidate_total_length_m)
    length_balance_ratio = _safe_ratio(candidate_total_length_m, reference_total_length_m)
    length_f1_ratio = _f1_ratio(candidate_match_ratio, reference_coverage_ratio)

    hausdorff_distance_m: float | None = None
    if (
        reference_union is not None
        and candidate_union is not None
        and (not reference_union.is_empty)
        and (not candidate_union.is_empty)
    ):
        value = float(reference_union.hausdorff_distance(candidate_union))
        if np.isfinite(value):
            hausdorff_distance_m = value

    return HydrographicNetworkComparison(
        tolerance_m=float(tolerance_m),
        crs=crs,
        reference_gdf=reference_gdf,
        candidate_gdf=candidate_gdf,
        reference_matched_gdf=reference_matched_gdf,
        reference_missing_gdf=reference_missing_gdf,
        candidate_matched_gdf=candidate_matched_gdf,
        candidate_extra_gdf=candidate_extra_gdf,
        reference_total_length_m=reference_total_length_m,
        candidate_total_length_m=candidate_total_length_m,
        matched_reference_length_m=matched_reference_length_m,
        matched_candidate_length_m=matched_candidate_length_m,
        missing_reference_length_m=missing_reference_length_m,
        extra_candidate_length_m=extra_candidate_length_m,
        reference_coverage_ratio=reference_coverage_ratio,
        candidate_match_ratio=candidate_match_ratio,
        missing_reference_ratio=missing_reference_ratio,
        extra_candidate_ratio=extra_candidate_ratio,
        length_balance_ratio=length_balance_ratio,
        length_f1_ratio=length_f1_ratio,
        hausdorff_distance_m=hausdorff_distance_m,
    )


def _coerce_network_gdf(network: HydrographicNetwork | GeoDataFrame) -> GeoDataFrame:
    import geopandas as gpd

    if isinstance(network, HydrographicNetwork):
        gdf = network.read_vector()
        if gdf is None:
            raise ValueError(
                f"Hydrographic network role='{network.role}' has no readable vector representation."
            )
        return gdf
    if isinstance(network, gpd.GeoDataFrame):
        return network
    raise TypeError("network must be a HydrographicNetwork or a GeoDataFrame")


def _normalize_linework(gdf: GeoDataFrame) -> GeoDataFrame:
    import geopandas as gpd

    if gdf.empty:
        return gpd.GeoDataFrame(geometry=[], crs=gdf.crs)

    geometries = []
    for geom in gdf.geometry:
        geometries.extend(_explode_linear_geometries(geom))
    return gpd.GeoDataFrame(geometry=geometries, crs=gdf.crs)


def _explode_linear_geometries(geom) -> list[object]:
    if geom is None or geom.is_empty:
        return []
    geom_type = str(getattr(geom, "geom_type", ""))
    if geom_type in {"LineString", "LinearRing"}:
        return [geom]
    if geom_type == "MultiLineString":
        return [part for part in geom.geoms if part is not None and not part.is_empty]
    if geom_type == "GeometryCollection":
        out: list[object] = []
        for part in geom.geoms:
            out.extend(_explode_linear_geometries(part))
        return out
    return []


def _line_boolean(gdf: GeoDataFrame, polygon, *, mode: str) -> GeoDataFrame:
    import geopandas as gpd

    if gdf.empty:
        return gpd.GeoDataFrame(geometry=[], crs=gdf.crs)
    if polygon is None or polygon.is_empty:
        return gdf.copy() if mode == "difference" else gpd.GeoDataFrame(geometry=[], crs=gdf.crs)

    geometries = []
    for geom in gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        result = geom.intersection(polygon) if mode == "intersection" else geom.difference(polygon)
        geometries.extend(_explode_linear_geometries(result))
    return gpd.GeoDataFrame(geometry=geometries, crs=gdf.crs)


def _network_length(gdf: GeoDataFrame) -> float:
    return measure_linework_length_m(gdf)


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator / denominator)


def _f1_ratio(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall <= 0:
        return 0.0
    return float((2.0 * precision * recall) / (precision + recall))


__all__ = [
    "HydrographicNetworkComparison",
    "compare_hydrographic_networks",
]
