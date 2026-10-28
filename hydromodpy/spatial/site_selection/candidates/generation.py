"""DEM-network candidate generation for site selection."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.io.crs import crs_text, ensure_crs
from hydromodpy.spatial.delineation.registry import (
    backend_has_callables,
    resolve_delineation_backend,
)
from hydromodpy.spatial.site_selection.config.dem_config import DemAreaLightConfig, HydrologyConfig
from hydromodpy.spatial.site_selection.config.outlets_config import OutletsConfig
from hydromodpy.spatial.site_selection.domain.candidate_outlet import CandidateOutlet
from hydromodpy.spatial.site_selection.hydrology.flow_products import SiteSelectionFlowProducts


@dataclass(frozen=True)
class CandidateGenerationEvidence:
    """Audit record explaining one generated network candidate."""

    candidate_id: str
    x: float
    y: float
    crs: str
    source: str
    raster_row: int
    raster_col: int
    accumulation_value: float
    threshold_value_used: float
    network_threshold_area_km2: float
    upstream_area_km2: float | None = None
    target_area_km2: float | None = None
    area_error_km2: float | None = None
    status: str = "accepted"
    rejection_reason: str = ""
    min_distance_between_outlets_km: float | None = None
    nearest_selected_candidate_id: str = ""
    nearest_selected_distance_m: float | None = None
    reference_network_source: str = ""
    reference_network_distance_m: float | None = None
    reference_network_score: float | None = None
    reference_network_status: str = ""
    rank: int = 0
    evidence_json: dict[str, Any] | None = None

    def to_record(self) -> dict[str, Any]:
        """Return a JSONL-friendly mapping."""

        return {
            "candidate_id": self.candidate_id,
            "x": self.x,
            "y": self.y,
            "crs": self.crs,
            "source": self.source,
            "raster_row": self.raster_row,
            "raster_col": self.raster_col,
            "accumulation_value": self.accumulation_value,
            "threshold_value_used": self.threshold_value_used,
            "network_threshold_area_km2": self.network_threshold_area_km2,
            "upstream_area_km2": self.upstream_area_km2,
            "target_area_km2": self.target_area_km2,
            "area_error_km2": self.area_error_km2,
            "status": self.status,
            "rejection_reason": self.rejection_reason,
            "min_distance_between_outlets_km": self.min_distance_between_outlets_km,
            "nearest_selected_candidate_id": self.nearest_selected_candidate_id,
            "nearest_selected_distance_m": self.nearest_selected_distance_m,
            "reference_network_source": self.reference_network_source,
            "reference_network_distance_m": self.reference_network_distance_m,
            "reference_network_score": self.reference_network_score,
            "reference_network_status": self.reference_network_status,
            "rank": self.rank,
            "evidence_json": dict(self.evidence_json or {}),
        }


def generate_network_candidate_outlets(
    *,
    flow_products: SiteSelectionFlowProducts,
    outlets: OutletsConfig,
    hydrology: HydrologyConfig,
    search_geometry: object | None = None,
    candidate_prefix: str = "network",
) -> tuple[list[CandidateOutlet], list[CandidateGenerationEvidence]]:
    """Generate candidate outlets from the DEM accumulation raster.

    The current implementation samples high-accumulation raster cells. It is a
    deterministic first pass for DEM-only campaigns; richer confluence or
    Strahler-based sampling can be added later without changing the downstream
    candidate contract.
    """

    raster = read_accumulation_raster(flow_products.products.acc)
    search_mask = search_geometry_mask(raster, search_geometry)
    valid_search_mask = (
        raster.valid_mask if search_mask is None else raster.valid_mask & search_mask
    )
    threshold = resolve_accumulation_threshold(
        raster,
        network_threshold_area_km2=hydrology.network_threshold_area_km2,
    )
    rows, cols = np.where(valid_search_mask & (raster.array >= threshold))
    if rows.size == 0:
        rows, cols = np.where(valid_search_mask)
    scored_cells = sorted(
        (
            (
                float(raster.array[int(row), int(col)]),
                int(row),
                int(col),
            )
            for row, col in zip(rows, cols, strict=True)
        ),
        reverse=True,
    )

    min_distance_m = None
    if outlets.min_distance_between_outlets_km is not None:
        min_distance_m = float(outlets.min_distance_between_outlets_km) * 1000.0
    max_count = outlets.max_generated_candidates
    max_rejected_audit = outlets.max_rejected_candidate_audit_records
    rejected_audit_count = 0

    candidates: list[CandidateOutlet] = []
    evidence: list[CandidateGenerationEvidence] = []
    for accumulation_value, row, col in scored_cells:
        x, y = raster.xy(row, col)
        nearest_candidate_id, nearest_distance_m = _nearest_candidate_distance(
            x,
            y,
            candidates,
        )
        if max_count is not None and len(candidates) >= int(max_count):
            if _can_audit_rejected(rejected_audit_count, max_rejected_audit):
                evidence.append(
                    _candidate_evidence(
                        candidate_id=f"{candidate_prefix}_rejected_{len(evidence) + 1:05d}",
                        x=x,
                        y=y,
                        raster=raster,
                        row=row,
                        col=col,
                        accumulation_value=accumulation_value,
                        threshold=threshold,
                        hydrology=hydrology,
                        outlets=outlets,
                        status="rejected",
                        rejection_reason="max_generated_candidates_reached",
                        nearest_selected_candidate_id=nearest_candidate_id,
                        nearest_selected_distance_m=nearest_distance_m,
                    )
                )
            break
        if (
            min_distance_m is not None
            and nearest_distance_m is not None
            and nearest_distance_m < min_distance_m
        ):
            if _can_audit_rejected(rejected_audit_count, max_rejected_audit):
                evidence.append(
                    _candidate_evidence(
                        candidate_id=f"{candidate_prefix}_rejected_{len(evidence) + 1:05d}",
                        x=x,
                        y=y,
                        raster=raster,
                        row=row,
                        col=col,
                        accumulation_value=accumulation_value,
                        threshold=threshold,
                        hydrology=hydrology,
                        outlets=outlets,
                        status="rejected",
                        rejection_reason="min_distance_between_outlets",
                        nearest_selected_candidate_id=nearest_candidate_id,
                        nearest_selected_distance_m=nearest_distance_m,
                    )
                )
                rejected_audit_count += 1
            continue
        rank = len(candidates) + 1
        candidate_id = f"{candidate_prefix}_{rank:05d}"
        attributes = {
            "candidate_generation_source": "dem_accumulation",
            "candidate_generation_rank": rank,
            "flow_accumulation_value": accumulation_value,
            "flow_accumulation_row": row,
            "flow_accumulation_col": col,
            "flow_accumulation_threshold_used": threshold,
            "network_threshold_area_km2": hydrology.network_threshold_area_km2,
        }
        candidates.append(
            CandidateOutlet(
                candidate_id=candidate_id,
                x=x,
                y=y,
                crs=raster.crs,
                source="network_sampling",
                source_feature_id=candidate_id,
                source_label=candidate_id,
                priority=accumulation_value,
                attributes=attributes,
            )
        )
        evidence.append(
            _candidate_evidence(
                candidate_id=candidate_id,
                x=x,
                y=y,
                raster=raster,
                row=row,
                col=col,
                accumulation_value=accumulation_value,
                threshold=threshold,
                hydrology=hydrology,
                outlets=outlets,
                status="accepted",
                rank=rank,
            )
        )
    return candidates, evidence


def generate_dem_area_light_candidate_outlets(
    *,
    flow_products: SiteSelectionFlowProducts,
    dem_area_light: DemAreaLightConfig,
    hydrology: HydrologyConfig,
    accumulation_cells_path: str | Path | None = None,
    search_geometry: object | None = None,
    candidate_prefix: str = "dem_area",
    max_candidates_before_delineation: int | None = None,
) -> tuple[list[CandidateOutlet], list[CandidateGenerationEvidence]]:
    """Generate DEM-only outlet candidates from raw upstream area."""

    acc_path = accumulation_cells_path or flow_products.products.acc
    raster = read_accumulation_raster(acc_path)
    if raster.looks_log_scaled:
        raise ValueError(
            "dem_area_light requires raw D8 accumulation in cell counts. "
            "The provided accumulation raster looks log-scaled."
        )

    upstream_area = accumulation_to_area_km2(
        raster.array,
        cell_area_m2=raster.cell_area_m2,
    )
    search_mask = search_geometry_mask(raster, search_geometry)
    valid_search_mask = (
        raster.valid_mask if search_mask is None else raster.valid_mask & search_mask
    )
    candidate_mask = (
        valid_search_mask
        & (upstream_area >= float(dem_area_light.min_area_km2))
        & (upstream_area <= float(dem_area_light.max_area_km2))
        & (upstream_area >= float(hydrology.network_threshold_area_km2))
    )
    rows, cols = np.where(candidate_mask)
    raw_candidate_count = int(rows.size)
    scored_cells = sorted(
        (
            (
                abs(float(upstream_area[int(row), int(col)]) - dem_area_light.target_area_km2),
                -float(upstream_area[int(row), int(col)]),
                int(row),
                int(col),
            )
            for row, col in zip(rows, cols, strict=True)
        ),
        key=lambda item: (item[0], item[1], item[2], item[3]),
    )

    min_distance_m = _default_dem_area_min_outlet_distance_m(dem_area_light.target_area_km2)
    max_count = max_candidates_before_delineation
    if max_count is None:
        max_count = max(int(dem_area_light.n_basins) * 20, int(dem_area_light.n_basins))

    candidates: list[CandidateOutlet] = []
    evidence: list[CandidateGenerationEvidence] = []
    rejected_audit_count = 0
    max_rejected_audit = 200
    for area_error_km2, _neg_area, row, col in scored_cells:
        x, y = raster.xy(row, col)
        nearest_candidate_id, nearest_distance_m = _nearest_candidate_distance(
            x,
            y,
            candidates,
        )
        if len(candidates) >= int(max_count):
            if _can_audit_rejected(rejected_audit_count, max_rejected_audit):
                evidence.append(
                    _dem_area_candidate_evidence(
                        candidate_id=f"{candidate_prefix}_rejected_{len(evidence) + 1:05d}",
                        x=x,
                        y=y,
                        raster=raster,
                        row=row,
                        col=col,
                        accumulation_value=float(raster.array[row, col]),
                        upstream_area_km2=float(upstream_area[row, col]),
                        area_error_km2=float(area_error_km2),
                        dem_area_light=dem_area_light,
                        hydrology=hydrology,
                        min_distance_m=min_distance_m,
                        raw_candidate_count=raw_candidate_count,
                        max_candidates_before_delineation=int(max_count),
                        status="rejected",
                        rejection_reason="max_candidates_before_delineation_reached",
                        nearest_selected_candidate_id=nearest_candidate_id,
                        nearest_selected_distance_m=nearest_distance_m,
                    )
                )
            break
        if nearest_distance_m is not None and nearest_distance_m < min_distance_m:
            if _can_audit_rejected(rejected_audit_count, max_rejected_audit):
                evidence.append(
                    _dem_area_candidate_evidence(
                        candidate_id=f"{candidate_prefix}_rejected_{len(evidence) + 1:05d}",
                        x=x,
                        y=y,
                        raster=raster,
                        row=row,
                        col=col,
                        accumulation_value=float(raster.array[row, col]),
                        upstream_area_km2=float(upstream_area[row, col]),
                        area_error_km2=float(area_error_km2),
                        dem_area_light=dem_area_light,
                        hydrology=hydrology,
                        min_distance_m=min_distance_m,
                        raw_candidate_count=raw_candidate_count,
                        max_candidates_before_delineation=int(max_count),
                        status="rejected",
                        rejection_reason="min_outlet_distance",
                        nearest_selected_candidate_id=nearest_candidate_id,
                        nearest_selected_distance_m=nearest_distance_m,
                    )
                )
                rejected_audit_count += 1
            continue

        rank = len(candidates) + 1
        candidate_id = f"{candidate_prefix}_{rank:05d}"
        accumulation_value = float(raster.array[row, col])
        upstream_area_km2 = float(upstream_area[row, col])
        priority = _area_priority(
            upstream_area_km2,
            target_area_km2=dem_area_light.target_area_km2,
            min_area_km2=dem_area_light.min_area_km2,
            max_area_km2=dem_area_light.max_area_km2,
        )
        attributes = {
            "candidate_generation_source": "dem_area_light",
            "candidate_generation_rank": rank,
            "flow_accumulation_cells": accumulation_value,
            "flow_accumulation_row": row,
            "flow_accumulation_col": col,
            "upstream_area_km2": upstream_area_km2,
            "target_area_km2": float(dem_area_light.target_area_km2),
            "area_error_km2": float(area_error_km2),
            "network_threshold_area_km2": float(hydrology.network_threshold_area_km2),
            "min_outlet_distance_m": min_distance_m,
        }
        candidates.append(
            CandidateOutlet(
                candidate_id=candidate_id,
                x=x,
                y=y,
                crs=raster.crs,
                source="dem_area_light",
                source_feature_id=candidate_id,
                source_label=candidate_id,
                priority=priority,
                attributes=attributes,
            )
        )
        evidence.append(
            _dem_area_candidate_evidence(
                candidate_id=candidate_id,
                x=x,
                y=y,
                raster=raster,
                row=row,
                col=col,
                accumulation_value=accumulation_value,
                upstream_area_km2=upstream_area_km2,
                area_error_km2=float(area_error_km2),
                dem_area_light=dem_area_light,
                hydrology=hydrology,
                min_distance_m=min_distance_m,
                raw_candidate_count=raw_candidate_count,
                max_candidates_before_delineation=int(max_count),
                status="accepted",
                rank=rank,
            )
        )
    return candidates, evidence


def accumulation_to_area_km2(
    accumulation_cells: np.ndarray,
    *,
    cell_area_m2: float,
) -> np.ndarray:
    """Convert raw accumulation cell counts to upstream area in square kilometres."""

    if cell_area_m2 <= 0.0:
        raise ValueError("cell_area_m2 must be > 0.")
    return np.asarray(accumulation_cells, dtype="float64") * float(cell_area_m2) / 1_000_000.0


def ensure_raw_accumulation_cells(
    *,
    flow_products: SiteSelectionFlowProducts,
    output_dir: str | Path,
    backend: object | None = None,
    crs_project: str | None = None,
) -> Path:
    """Return a raw-cell accumulation raster, creating it when the default one is log-scaled."""

    existing = Path(flow_products.products.acc)
    if existing.is_file():
        try:
            if not read_accumulation_raster(existing).looks_log_scaled:
                return existing
        except Exception:
            pass

    destination = Path(output_dir) / "dem_acc_cells.tif"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        return destination

    tool = resolve_delineation_backend(backend)
    products = flow_products.products
    if backend_has_callables(
        tool, "raster", "read_raster", "write_raster"
    ) and backend_has_callables(
        tool,
        "flow",
        "d8_flow_accumulation_raster",
    ):
        correc_data = tool.raster.read_raster(str(products.correc))
        acc_data = tool.flow.d8_flow_accumulation_raster(correc_data, log=False)
        tool.raster.write_raster(acc_data, str(destination))
    else:
        if not backend_has_callables(tool, "flow", "d8_flow_accumulation"):
            raise TypeError(
                "dem_area_light requires a delineation backend with "
                "flow.d8_flow_accumulation or flow.d8_flow_accumulation_raster."
            )
        tool.flow.d8_flow_accumulation(
            str(products.correc),
            str(destination),
            log=False,
        )
    ensure_crs(destination, crs_project)
    return destination


def candidate_generation_evidence_with_candidate_attributes(
    evidence: Iterable[CandidateGenerationEvidence],
    candidates: Iterable[CandidateOutlet],
) -> list[CandidateGenerationEvidence]:
    """Copy reference-network scoring attributes from candidates to audit rows."""

    attributes_by_id = {candidate.candidate_id: candidate.attributes for candidate in candidates}
    updated: list[CandidateGenerationEvidence] = []
    for row in evidence:
        attributes = attributes_by_id.get(row.candidate_id)
        if not attributes:
            updated.append(row)
            continue
        updated.append(
            replace(
                row,
                reference_network_source=str(
                    attributes.get("reference_network_source") or row.reference_network_source
                ),
                reference_network_distance_m=_optional_float(
                    attributes.get("reference_network_distance_m")
                ),
                reference_network_score=_optional_float(attributes.get("reference_network_score")),
                reference_network_status=str(
                    attributes.get("reference_network_status") or row.reference_network_status
                ),
            )
        )
    return updated


@dataclass(frozen=True)
class AccumulationRaster:
    array: np.ndarray
    valid_mask: np.ndarray
    transform: Any
    crs: str
    pixel_width_m: float
    pixel_height_m: float
    looks_log_scaled: bool

    @property
    def cell_area_m2(self) -> float:
        return self.pixel_width_m * self.pixel_height_m

    def xy(self, row: int, col: int) -> tuple[float, float]:
        import rasterio.transform

        x, y = rasterio.transform.xy(self.transform, row, col, offset="center")
        return float(x), float(y)


def read_accumulation_raster(path: str | Path) -> AccumulationRaster:
    import rasterio

    with rasterio.open(str(path)) as src:
        array = np.asarray(src.read(1), dtype="float64")
        nodata = src.nodata
        transform = src.transform
        crs = crs_text(src.crs) or ""
    valid = np.isfinite(array)
    if nodata is not None:
        valid &= array != float(nodata)
    valid &= array > 0.0
    finite_positive = array[valid]
    looks_log_scaled = bool(finite_positive.size > 0 and float(np.nanmax(finite_positive)) < 100.0)
    return AccumulationRaster(
        array=array,
        valid_mask=valid,
        transform=transform,
        crs=crs,
        pixel_width_m=abs(float(transform.a)),
        pixel_height_m=abs(float(transform.e)),
        looks_log_scaled=looks_log_scaled,
    )


def search_geometry_mask(
    raster: AccumulationRaster,
    search_geometry: object | None,
) -> np.ndarray | None:
    if search_geometry is None:
        return None
    if bool(getattr(search_geometry, "is_empty", False)):
        return np.zeros(raster.array.shape, dtype=bool)
    import rasterio.features
    from shapely.geometry import mapping

    return rasterio.features.geometry_mask(
        [mapping(search_geometry)],
        out_shape=raster.array.shape,
        transform=raster.transform,
        invert=True,
    )


def resolve_accumulation_threshold(
    raster: AccumulationRaster,
    *,
    network_threshold_area_km2: float,
) -> float:
    cell_area_m2 = raster.pixel_width_m * raster.pixel_height_m
    threshold_cells = float(network_threshold_area_km2) * 1_000_000.0 / cell_area_m2
    if raster.looks_log_scaled:
        threshold = math.log(max(1.0, threshold_cells))
    else:
        threshold = threshold_cells
    values = raster.array[raster.valid_mask]
    if values.size == 0:
        return threshold
    max_value = float(np.nanmax(values))
    if max_value >= threshold:
        return float(threshold)
    return float(np.nanpercentile(values, 90.0))


def _candidate_evidence(
    *,
    candidate_id: str,
    x: float,
    y: float,
    raster: AccumulationRaster,
    row: int,
    col: int,
    accumulation_value: float,
    threshold: float,
    hydrology: HydrologyConfig,
    outlets: OutletsConfig,
    status: str,
    rejection_reason: str = "",
    nearest_selected_candidate_id: str = "",
    nearest_selected_distance_m: float | None = None,
    rank: int = 0,
) -> CandidateGenerationEvidence:
    return CandidateGenerationEvidence(
        candidate_id=candidate_id,
        x=x,
        y=y,
        crs=raster.crs,
        source="dem_accumulation",
        raster_row=row,
        raster_col=col,
        accumulation_value=accumulation_value,
        threshold_value_used=threshold,
        network_threshold_area_km2=hydrology.network_threshold_area_km2,
        status=status,
        rejection_reason=rejection_reason,
        min_distance_between_outlets_km=outlets.min_distance_between_outlets_km,
        nearest_selected_candidate_id=nearest_selected_candidate_id,
        nearest_selected_distance_m=nearest_selected_distance_m,
        rank=rank,
        evidence_json={
            "accumulation_is_log_scaled": raster.looks_log_scaled,
            "pixel_width_m": raster.pixel_width_m,
            "pixel_height_m": raster.pixel_height_m,
        },
    )


def _dem_area_candidate_evidence(
    *,
    candidate_id: str,
    x: float,
    y: float,
    raster: AccumulationRaster,
    row: int,
    col: int,
    accumulation_value: float,
    upstream_area_km2: float,
    area_error_km2: float,
    dem_area_light: DemAreaLightConfig,
    hydrology: HydrologyConfig,
    min_distance_m: float,
    raw_candidate_count: int,
    max_candidates_before_delineation: int,
    status: str,
    rejection_reason: str = "",
    nearest_selected_candidate_id: str = "",
    nearest_selected_distance_m: float | None = None,
    rank: int = 0,
) -> CandidateGenerationEvidence:
    return CandidateGenerationEvidence(
        candidate_id=candidate_id,
        x=x,
        y=y,
        crs=raster.crs,
        source="dem_area_light",
        raster_row=row,
        raster_col=col,
        accumulation_value=accumulation_value,
        threshold_value_used=hydrology.network_threshold_area_km2,
        network_threshold_area_km2=hydrology.network_threshold_area_km2,
        upstream_area_km2=upstream_area_km2,
        target_area_km2=dem_area_light.target_area_km2,
        area_error_km2=area_error_km2,
        status=status,
        rejection_reason=rejection_reason,
        min_distance_between_outlets_km=min_distance_m / 1000.0,
        nearest_selected_candidate_id=nearest_selected_candidate_id,
        nearest_selected_distance_m=nearest_selected_distance_m,
        rank=rank,
        evidence_json={
            "accumulation_is_log_scaled": raster.looks_log_scaled,
            "raw_candidate_cells": raw_candidate_count,
            "max_candidates_before_delineation": max_candidates_before_delineation,
            "pixel_width_m": raster.pixel_width_m,
            "pixel_height_m": raster.pixel_height_m,
            "cell_area_m2": raster.cell_area_m2,
        },
    )


def _default_dem_area_min_outlet_distance_m(target_area_km2: float) -> float:
    """Derive outlet spacing from half the characteristic basin length."""

    return 0.5 * math.sqrt(float(target_area_km2)) * 1000.0


def _area_priority(
    upstream_area_km2: float,
    *,
    target_area_km2: float,
    min_area_km2: float,
    max_area_km2: float,
) -> float:
    half_width = max(
        float(target_area_km2) - float(min_area_km2),
        float(max_area_km2) - float(target_area_km2),
        1.0e-12,
    )
    normalized = abs(float(upstream_area_km2) - float(target_area_km2)) / half_width
    return max(0.0, 1.0 - normalized)


def _nearest_candidate_distance(
    x: float,
    y: float,
    candidates: Iterable[CandidateOutlet],
) -> tuple[str, float | None]:
    nearest_id = ""
    nearest_distance: float | None = None
    for candidate in candidates:
        distance = math.hypot(x - float(candidate.x), y - float(candidate.y))
        if nearest_distance is None or distance < nearest_distance:
            nearest_id = candidate.candidate_id
            nearest_distance = distance
    return nearest_id, nearest_distance


def _can_audit_rejected(count: int, limit: int | None) -> bool:
    return limit is None or count < int(limit)


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "CandidateGenerationEvidence",
    "accumulation_to_area_km2",
    "candidate_generation_evidence_with_candidate_attributes",
    "ensure_raw_accumulation_cells",
    "generate_dem_area_light_candidate_outlets",
    "generate_network_candidate_outlets",
]
