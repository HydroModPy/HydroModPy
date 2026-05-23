"""Composable build pipeline for site selection."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.spatial.geographic.core.catchment_from_point import (
    CatchmentFromPointProducts,
)
from hydromodpy.spatial.geographic.core.flow_products import build_regional_flow_products
from hydromodpy.spatial.site_selection.artifacts import write_manifest_and_optional_report
from hydromodpy.spatial.site_selection.candidate_outlets import (
    CandidateOutlet,
    candidate_outlets_from_point_records,
    thin_candidate_outlets,
)
from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.delineation import (
    DelineatedCatchment,
    try_delineate_candidate_outlet,
)
from hydromodpy.spatial.site_selection.exports import (
    write_observation_points_geojson,
    write_selection_result,
)
from hydromodpy.spatial.site_selection.flow_products_adapter import (
    FlowProductsBuilder,
    SiteSelectionFlowProducts,
    build_site_selection_flow_products,
)
from hydromodpy.spatial.site_selection.observations import build_observation_evidence
from hydromodpy.spatial.site_selection.selection import (
    SelectionResult,
    select_delineated_catchments,
)
from hydromodpy.spatial.site_selection.types import ObservationEvidence


@dataclass(frozen=True)
class SiteSelectionBuildResult:
    """Result of an end-to-end site-selection build from already-loaded observations."""

    candidates: list[CandidateOutlet]
    delineated: list[DelineatedCatchment]
    observation_evidence: list[ObservationEvidence]
    selection: SelectionResult
    output_paths: dict[str, Path]
    flow_products: SiteSelectionFlowProducts


def build_site_selection_from_point_records(
    *,
    config: SiteSelectionConfig,
    point_records: Iterable[Any],
    dem_init_path: str | Path | None = None,
    output_root: str | Path | None = None,
    crs_project: str | None = None,
    backend: object | None = None,
    flow_products_builder: FlowProductsBuilder | None = None,
    delineation_builder=None,
    area_reader=None,
    write_outputs: bool = True,
) -> SiteSelectionBuildResult:
    """Run station-led site selection from loaded ``PointRecord`` objects.

    The function deliberately receives records rather than fetching Hub'Eau
    itself. Existing data managers remain responsible for API/cache concerns.
    """

    records = list(point_records)
    root = Path(output_root) if output_root is not None else config.output_root
    root = root.expanduser().resolve()
    dem_path = Path(dem_init_path or config.dem.path).expanduser().resolve() if (
        dem_init_path or config.dem.path
    ) else None
    if dem_path is None:
        raise ValueError("build_site_selection_from_point_records requires dem_init_path or dem.path.")
    target_crs = crs_project or _read_raster_crs(dem_path) or _default_project_crs(config)

    candidates = candidate_outlets_from_point_records(
        records,
        candidate_prefix="station",
        source="station_outlets",
        target_crs=target_crs,
    )
    if config.outlets.min_distance_between_outlets_km is not None:
        candidates = thin_candidate_outlets(
            candidates,
            min_distance_km=config.outlets.min_distance_between_outlets_km,
        )

    flow_products = build_site_selection_flow_products(
        dem_init_path=dem_path,
        output_dir=root / "flow_products",
        hydrology=config.hydrology,
        crs_project=target_crs,
        backend=backend,
        builder=flow_products_builder or build_regional_flow_products,
    )

    delineated = [
        try_delineate_candidate_outlet(
            outlet=candidate,
            flow_products=flow_products,
            output_root=root / "catchments",
            snap_dist_m=config.outlets.snap_dist_m,
            crs_project=target_crs or candidate.crs,
            site_id=candidate.candidate_id,
            backend=backend,
            builder=delineation_builder or _default_delineation_builder,
            area_reader=area_reader,
        )
        for candidate in candidates
    ]
    selection = select_delineated_catchments(
        delineated,
        criteria=config.criteria,
        spatial_selection=config.spatial_selection,
        selection_principle=config.strategy.principle,
    )
    observation_evidence = _observation_evidence_for_candidates(
        candidates=candidates,
        records=records,
    )
    output_paths: dict[str, Path] = {}
    if write_outputs:
        output_paths = write_selection_result(
            root,
            selection,
            selection_id=config.selection_id,
            region_id=_first_region_id(config),
            write_selected=config.output.write_csv and config.output.write_selected,
            write_rejected=config.output.write_csv and config.output.write_rejected,
            write_regional_lab_csv_output=config.output.write_regional_lab_csv,
            write_geojson=config.output.write_geojson,
        )
        output_paths["observation_evidence_jsonl"] = _write_observation_evidence_jsonl(
            root / "observation_evidence.jsonl",
            observation_evidence,
        )
        if config.output.write_geojson:
            output_paths["observation_points_geojson"] = write_observation_points_geojson(
                root / "observation_points.geojson",
                observation_evidence,
            )
        flow_manifest = flow_products.to_manifest_record()
        flow_manifest["dem_path"] = str(dem_path)
        flow_manifest["dem_source"] = config.dem.source
        output_paths.update(
            write_manifest_and_optional_report(
                config=config.model_copy(update={"output_root": root}),
                selection=selection,
                output_paths=output_paths,
                action="hydrometry",
                flow_products=flow_manifest,
            )
        )

    return SiteSelectionBuildResult(
        candidates=candidates,
        delineated=delineated,
        observation_evidence=observation_evidence,
        selection=selection,
        output_paths=output_paths,
        flow_products=flow_products,
    )


def _observation_evidence_for_candidates(
    *,
    candidates: list[CandidateOutlet],
    records: list[Any],
) -> list[ObservationEvidence]:
    record_by_id = {str(getattr(record, "station_id", "")): record for record in records}
    evidence: list[ObservationEvidence] = []
    for candidate in candidates:
        record = record_by_id.get(candidate.source_feature_id)
        if record is None:
            continue
        evidence.extend(
            build_observation_evidence(
                site_id=candidate.candidate_id,
                observation_type="flow_station",
                records=[record],
            )
        )
    return evidence


def _write_observation_evidence_jsonl(
    path: str | Path,
    evidence: Iterable[ObservationEvidence],
) -> Path:
    import json

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for row in evidence:
            handle.write(json.dumps(row.to_record(), ensure_ascii=True, sort_keys=True) + "\n")
    return destination


def _first_region_id(config: SiteSelectionConfig) -> str:
    if config.territory.regions:
        return config.territory.regions[0]
    if config.territory.departments:
        return config.territory.departments[0]
    return ""


def _default_delineation_builder(**kwargs) -> CatchmentFromPointProducts:
    from hydromodpy.spatial.geographic.core.catchment_from_point import (
        extract_catchment_from_point,
    )

    return extract_catchment_from_point(**kwargs)


def _read_raster_crs(path: Path) -> str | None:
    """Read a DEM CRS when the path points to a real raster."""

    try:
        import rasterio

        with rasterio.open(path) as src:
            return None if src.crs is None else str(src.crs)
    except Exception:
        return None


def _default_project_crs(config: SiteSelectionConfig) -> str | None:
    if (config.territory.country or "").upper() == "FR":
        return "EPSG:2154"
    return None


__all__ = [
    "SiteSelectionBuildResult",
    "build_site_selection_from_point_records",
]
