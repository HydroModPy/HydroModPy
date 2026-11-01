"""Composable build pipeline for site selection."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import rasterio

from hydromodpy.core.io.crs import crs_text
from hydromodpy.site_selection.candidates.generation import CandidateGenerationEvidence
from hydromodpy.site_selection.candidates.pipeline import (
    GeneratedCandidateResult,
    build_dem_area_light_candidates,
    build_generated_network_candidates,
    build_station_candidate_outlets,
    default_project_crs,
    first_candidate_crs,
    load_reference_network_for_station_candidates,
    require_lambert93_extent,
    site_selection_search_geometry,
)
from hydromodpy.site_selection.config.criteria_config import (
    AreaCriteriaConfig,
    CriteriaConfig,
)
from hydromodpy.site_selection.config.outlets_config import SpatialSelectionConfig
from hydromodpy.site_selection.config.site_selection_config import SiteSelectionConfig
from hydromodpy.site_selection.domain.candidate_outlet import CandidateOutlet
from hydromodpy.site_selection.domain.delineated_catchment import DelineatedCatchment
from hydromodpy.site_selection.domain.observation_evidence import ObservationEvidence
from hydromodpy.site_selection.domain.watershed import watershed_geometry
from hydromodpy.site_selection.evaluation.selection import (
    SelectionResult,
    select_delineated_catchments,
)
from hydromodpy.site_selection.evidence.annotations import (
    annotate_site_selection_catchments,
)
from hydromodpy.site_selection.evidence.observations import (
    build_observation_evidence,
    build_observation_evidence_from_attributes,
)
from hydromodpy.site_selection.hydrology.delineation import (
    delineate_site_selection_candidates,
)
from hydromodpy.site_selection.hydrology.flow_products import (
    FlowProductsBuilder,
    SiteSelectionFlowProducts,
    build_site_selection_flow_products,
)
from hydromodpy.site_selection.hydrology.reference_network import ReferenceNetworkFetcher
from hydromodpy.site_selection.outputs.candidate_files import (
    write_candidate_generation_jsonl,
    write_candidate_outlets_geojson,
    write_generated_network_geojson,
)
from hydromodpy.site_selection.outputs.cleanup import (
    cleanup_site_selection_intermediate_rasters,
)
from hydromodpy.site_selection.outputs.manifest import write_manifest_and_optional_report
from hydromodpy.site_selection.outputs.writer import (
    write_core_site_selection_outputs,
    write_csv,
)
from hydromodpy.spatial.geographic.core.flow_products import build_regional_flow_products

DEM_AREA_LIGHT_SNAP_DIST_M = 1
"""Snap distance of a DEM-area outlet, in metres.

A DEM-area candidate already sits on the centre of the accumulation cell chosen
for its drained area, so the delineation keeps it on that cell.
"""

_BUILD_OF_ACTION = {
    "hydrometry": "build_site_selection_from_point_records",
    "generated_candidates": "build_site_selection_from_generated_network",
    "dem_area_light": "build_site_selection_from_dem_area_light",
}

ExtraOutputs = Callable[[list[DelineatedCatchment], SelectionResult], dict[str, Path]]
"""Writes the files a candidate generation adds and returns their paths."""


@dataclass(frozen=True)
class SiteSelectionBuildResult:
    """Result of an end-to-end site-selection build from already-loaded observations."""

    candidates: list[CandidateOutlet]
    delineated: list[DelineatedCatchment]
    observation_evidence: list[ObservationEvidence]
    selection: SelectionResult
    output_paths: dict[str, Path]
    flow_products: SiteSelectionFlowProducts
    candidate_generation_evidence: list[CandidateGenerationEvidence] | None = None


def build_site_selection_from_point_records(
    *,
    config: SiteSelectionConfig,
    point_records: Iterable[Any],
    reference_network_fetcher: ReferenceNetworkFetcher,
    dem_init_path: str | Path | None = None,
    output_root: str | Path | None = None,
    crs_project: str | None = None,
    backend: object | None = None,
    flow_products_builder: FlowProductsBuilder | None = None,
    delineation_builder=None,
    area_reader=None,
    write_outputs: bool = True,
    report_renderer: Callable[[str | Path], Path] | None = None,
) -> SiteSelectionBuildResult:
    """Run station-led site selection from loaded ``PointRecord`` objects.

    The function deliberately receives records rather than fetching Hub'Eau
    itself. Existing data managers remain responsible for API/cache concerns,
    and *reference_network_fetcher* downloads BD Topage when the outlets snap on it.
    """

    return _run_selection(
        "hydrometry",
        config=config,
        point_records=list(point_records),
        reference_network_fetcher=reference_network_fetcher,
        dem_init_path=dem_init_path,
        output_root=output_root,
        crs_project=crs_project,
        backend=backend,
        flow_products_builder=flow_products_builder,
        delineation_builder=delineation_builder,
        area_reader=area_reader,
        write_outputs=write_outputs,
        report_renderer=report_renderer,
    )


def build_site_selection_from_generated_network(
    *,
    config: SiteSelectionConfig,
    reference_network_fetcher: ReferenceNetworkFetcher,
    dem_init_path: str | Path | None = None,
    output_root: str | Path | None = None,
    crs_project: str | None = None,
    backend: object | None = None,
    flow_products_builder: FlowProductsBuilder | None = None,
    delineation_builder=None,
    area_reader=None,
    write_outputs: bool = True,
    report_renderer: Callable[[str | Path], Path] | None = None,
) -> SiteSelectionBuildResult:
    """Run DEM/network-generated site selection without station or CSV candidates.

    *reference_network_fetcher* downloads BD Topage when the candidates snap on it or are
    scored against it.
    """

    return _run_selection(
        "generated_candidates",
        config=config,
        reference_network_fetcher=reference_network_fetcher,
        dem_init_path=dem_init_path,
        output_root=output_root,
        crs_project=crs_project,
        backend=backend,
        flow_products_builder=flow_products_builder,
        delineation_builder=delineation_builder,
        area_reader=area_reader,
        write_outputs=write_outputs,
        report_renderer=report_renderer,
    )


def build_site_selection_from_dem_area_light(
    *,
    config: SiteSelectionConfig,
    dem_init_path: str | Path | None = None,
    output_root: str | Path | None = None,
    crs_project: str | None = None,
    backend: object | None = None,
    flow_products_builder: FlowProductsBuilder | None = None,
    raw_accumulation_builder=None,
    delineation_builder=None,
    area_reader=None,
    write_outputs: bool = True,
    report_renderer: Callable[[str | Path], Path] | None = None,
) -> SiteSelectionBuildResult:
    """Run the lightweight DEM-only basin-area selection workflow."""

    if config.dem_area_light is None:
        raise ValueError("build_site_selection_from_dem_area_light requires dem_area_light config.")
    return _run_selection(
        "dem_area_light",
        config=config,
        dem_init_path=dem_init_path,
        output_root=output_root,
        crs_project=crs_project,
        backend=backend,
        flow_products_builder=flow_products_builder,
        raw_accumulation_builder=raw_accumulation_builder,
        delineation_builder=delineation_builder,
        area_reader=area_reader,
        write_outputs=write_outputs,
        report_renderer=report_renderer,
    )


def select_catchments_and_write_outputs(
    catchments: list[DelineatedCatchment],
    *,
    config: SiteSelectionConfig,
    root: Path,
    action: str,
    region_id: str,
    flow_manifest: dict[str, Any],
    manifest_config: SiteSelectionConfig | None = None,
    observation_evidence: list[ObservationEvidence] | None = None,
    criteria: CriteriaConfig | None = None,
    spatial_selection: SpatialSelectionConfig | None = None,
    basin_geometries: dict[str, object] | None = None,
    write_outputs: bool = True,
    write_evidence_vectors: bool = True,
    extra_outputs: ExtraOutputs | None = None,
    input_paths: dict[str, str | Path | None] | None = None,
    flow_products: SiteSelectionFlowProducts | None = None,
    report_renderer: Callable[[str | Path], Path] | None = None,
) -> tuple[list[DelineatedCatchment], SelectionResult, list[ObservationEvidence], dict[str, Path]]:
    """Annotate and select delineated catchments, then write every output under *root*.

    The catchments are annotated with the context layers of ``config.criteria``,
    then selected with *criteria* and *spatial_selection* when given. The
    observation evidence is *observation_evidence* plus the piezometers found
    by the annotation. ``None`` reads it from the outlet attributes of the
    annotated catchments, as a pre-delineated CSV carries them.

    With *write_outputs*, the core outputs, the files of *extra_outputs*, the
    manifest of *action* and the optional report are written, then the
    intermediate rasters are removed unless the config keeps them. The manifest
    reads *manifest_config*, by default the config with its output root set
    to *root*. Returns the annotated catchments, the selection, the evidence and
    the written paths.
    """

    annotations = annotate_site_selection_catchments(catchments, criteria=config.criteria)
    catchments = annotations.catchments
    selection = select_delineated_catchments(
        catchments,
        criteria=config.criteria if criteria is None else criteria,
        spatial_selection=(
            config.spatial_selection if spatial_selection is None else spatial_selection
        ),
        selection_principle=config.strategy.principle,
        basin_geometries=basin_geometries,
    )
    if observation_evidence is None:
        observation_evidence = [
            evidence
            for catchment in catchments
            for evidence in build_observation_evidence_from_attributes(
                site_id=catchment.site_id,
                attributes=catchment.outlet.attributes,
            )
        ]
    observation_evidence = [*observation_evidence, *annotations.piezometer_evidence]
    output_paths: dict[str, Path] = {}
    if not write_outputs:
        return catchments, selection, observation_evidence, output_paths

    output_paths = write_core_site_selection_outputs(
        root,
        config=config,
        selection=selection,
        region_id=region_id,
        observation_evidence=observation_evidence,
        piezometer_evidence=annotations.piezometer_evidence,
        influence_evidence=annotations.influence_evidence,
        geology_evidence=annotations.geology_evidence,
        write_observation_vectors=write_evidence_vectors,
        write_context_vectors=write_evidence_vectors,
    )
    if extra_outputs is not None:
        output_paths.update(extra_outputs(catchments, selection))
    output_paths.update(
        write_manifest_and_optional_report(
            config=(
                config.model_copy(update={"output_root": root})
                if manifest_config is None
                else manifest_config
            ),
            selection=selection,
            output_paths=output_paths,
            action=action,
            input_paths=input_paths,
            flow_products=flow_manifest,
            report_renderer=report_renderer,
        )
    )
    if not config.output.keep_intermediate_rasters:
        cleanup_site_selection_intermediate_rasters(
            output_root=root,
            catchments=catchments,
            flow_products=flow_products,
        )
    return catchments, selection, observation_evidence, output_paths


def _run_selection(
    action: str,
    *,
    config: SiteSelectionConfig,
    point_records: list[Any] | None = None,
    reference_network_fetcher: ReferenceNetworkFetcher | None = None,
    dem_init_path: str | Path | None,
    output_root: str | Path | None,
    crs_project: str | None,
    backend: object | None,
    flow_products_builder: FlowProductsBuilder | None,
    raw_accumulation_builder=None,
    delineation_builder,
    area_reader,
    write_outputs: bool,
    report_renderer: Callable[[str | Path], Path] | None,
) -> SiteSelectionBuildResult:
    """Run one selection: flow products, candidates, delineation, selection, outputs.

    *action* names the candidates: ``hydrometry`` takes the stations of
    *point_records*, ``generated_candidates`` samples the DEM network and
    ``dem_area_light`` scans the DEM for basins of the target area.
    """

    root = Path(output_root) if output_root is not None else config.output_root
    root = root.expanduser().resolve()
    dem_path = (
        Path(dem_init_path or config.dem.path).expanduser().resolve()
        if (dem_init_path or config.dem.path)
        else None
    )
    if dem_path is None:
        raise ValueError(f"{_BUILD_OF_ACTION[action]} requires dem_init_path or dem.path.")
    dem_crs, dem_bounds = _read_raster_frame(dem_path)
    target_crs = crs_project or dem_crs or _default_crs(config, dem_path, dem_bounds)
    stations = action == "hydrometry"
    light = action == "dem_area_light"
    station_candidates: list[CandidateOutlet] = []
    search_geometry = None
    if stations:
        station_candidates = build_station_candidate_outlets(
            point_records or [],
            config=config,
            target_crs=target_crs,
        )
    else:
        search_geometry = site_selection_search_geometry(config, target_crs=target_crs)

    flow_products = build_site_selection_flow_products(
        dem_init_path=dem_path,
        output_dir=root / "flow_products",
        hydrology=config.hydrology,
        crs_project=target_crs,
        backend=backend,
        engine_id=config.terrain_engine,
        builder=flow_products_builder or build_regional_flow_products,
    )
    if stations:
        network, bundle = load_reference_network_for_station_candidates(
            config=config,
            candidates=station_candidates,
            target_crs=target_crs or first_candidate_crs(station_candidates),
            root=root,
            fetcher=reference_network_fetcher,
        )
        found = GeneratedCandidateResult(
            candidates=station_candidates,
            evidence=[],
            reference_network=network,
            reference_bundle=bundle,
        )
    elif light:
        found = build_dem_area_light_candidates(
            config=config,
            flow_products=flow_products.products,
            target_crs=target_crs,
            root=root,
            search_geometry=search_geometry,
            backend=backend,
            raw_accumulation_builder=raw_accumulation_builder,
        )
    else:
        found = build_generated_network_candidates(
            config=config,
            flow_products=flow_products.products,
            target_crs=target_crs,
            root=root,
            search_geometry=search_geometry,
            reference_network_fetcher=reference_network_fetcher,
        )
    candidates = found.candidates
    bundle = found.reference_bundle

    delineated = delineate_site_selection_candidates(
        candidates,
        flow_products=flow_products,
        output_root=root / "catchments",
        snap_dist_m=DEM_AREA_LIGHT_SNAP_DIST_M if light else config.outlets.snap_dist_m,
        crs_project=target_crs or first_candidate_crs(candidates),
        backend=backend,
        engine_id=config.terrain_engine,
        delineation_builder=delineation_builder,
        area_reader=area_reader,
        reference_network=(
            found.reference_network if config.outlets.snap_strategy == "bdtopage_then_dem" else None
        ),
        reference_network_source="" if bundle is None else bundle.source,
        reference_network_max_distance_m=config.outlets.reference_network_max_distance_m,
    )

    flow_manifest: dict[str, Any] = {}
    if write_outputs:
        flow_manifest = flow_products.to_manifest_record()
        flow_manifest["dem_path"] = str(dem_path)
        flow_manifest["dem_source"] = config.dem.source
        flow_manifest["intermediate_rasters_kept"] = config.output.keep_intermediate_rasters
        if bundle is not None:
            flow_manifest["reference_network"] = bundle.to_manifest_record()
        if light:
            flow_manifest["raw_flow_accumulation_cells_path"] = str(found.raw_accumulation_path)
            flow_manifest["dem_area_light"] = config.dem_area_light.model_dump(mode="json")

    def candidate_files(
        catchments: list[DelineatedCatchment],
        selection: SelectionResult,
    ) -> dict[str, Path]:
        paths = {
            "candidate_generation_jsonl": write_candidate_generation_jsonl(
                root / "candidate_generation.jsonl",
                found.evidence,
            )
        }
        if light:
            paths["diagnostics_csv"] = write_csv(
                root / "diagnostics.csv",
                _dem_area_light_diagnostic_rows(
                    candidates=candidates,
                    evidence=found.evidence,
                    delineated=catchments,
                    selection=selection,
                ),
                fieldnames=["metric", "count"],
            )
        if config.output.write_geojson:
            paths["candidate_outlets_geojson"] = write_candidate_outlets_geojson(
                root / "candidate_outlets.geojson",
                candidates,
            )
            paths["generated_network_geojson"] = write_generated_network_geojson(
                root / "generated_dem_network.geojson",
                flow_products=flow_products,
                hydrology=config.hydrology,
                max_cells=config.outlets.max_generated_network_cells,
                search_geometry=search_geometry,
            )
        return paths

    delineated, selection, observation_evidence, output_paths = select_catchments_and_write_outputs(
        delineated,
        config=config,
        root=root,
        action=action,
        region_id=_first_region_id(config),
        flow_manifest=flow_manifest,
        observation_evidence=(
            _observation_evidence_for_candidates(candidates=candidates, records=point_records)
            if stations
            else []
        ),
        criteria=_dem_area_light_criteria(config) if light else None,
        spatial_selection=_dem_area_light_spatial_selection(config) if light else None,
        basin_geometries=_load_basin_geometries(delineated) if light else None,
        write_outputs=write_outputs,
        write_evidence_vectors=not light,
        extra_outputs=None if stations else candidate_files,
        flow_products=flow_products,
        report_renderer=report_renderer,
    )
    return SiteSelectionBuildResult(
        candidates=candidates,
        delineated=delineated,
        observation_evidence=observation_evidence,
        selection=selection,
        output_paths=output_paths,
        flow_products=flow_products,
        candidate_generation_evidence=None if stations else found.evidence,
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


def _first_region_id(config: SiteSelectionConfig) -> str:
    if config.territory.regions:
        return config.territory.regions[0]
    if config.territory.departments:
        return config.territory.departments[0]
    return ""


def _dem_area_light_criteria(config: SiteSelectionConfig):
    dem_area = config.dem_area_light
    if dem_area is None:
        return config.criteria
    area = AreaCriteriaConfig(
        mode="hard_reject",
        target_area_km2=dem_area.target_area_km2,
        preferred_area_km2=dem_area.target_area_km2,
        hard_min_area_km2=dem_area.min_area_km2,
        hard_max_area_km2=dem_area.max_area_km2,
    )
    return config.criteria.model_copy(update={"area": area})


def _dem_area_light_spatial_selection(config: SiteSelectionConfig):
    current = config.spatial_selection
    return current.model_copy(
        update={
            "allow_nested_basins": False,
            "max_pairwise_basin_overlap_fraction": (
                current.max_pairwise_basin_overlap_fraction
                if current.max_pairwise_basin_overlap_fraction is not None
                else 0.10
            ),
            "overlap_reference": "smaller_basin",
            "overlap_mode": "hard_reject",
            "max_selected_sites": config.dem_area_light.n_basins
            if config.dem_area_light is not None
            else current.max_selected_sites,
        }
    )


def _load_basin_geometries(catchments: list[DelineatedCatchment]) -> dict[str, object]:
    geometries: dict[str, object] = {}
    for catchment in catchments:
        if catchment.status != "delineated":
            continue
        try:
            geometry = watershed_geometry(catchment.watershed_shp)
        except Exception:
            # A basin that cannot be read only loses its overlap check.
            continue
        if geometry is not None:
            geometries[catchment.site_id] = geometry
    return geometries


def _dem_area_light_diagnostic_rows(
    *,
    candidates: list[CandidateOutlet],
    evidence: list[CandidateGenerationEvidence],
    delineated: list[DelineatedCatchment],
    selection: SelectionResult,
) -> list[dict[str, int | str]]:
    raw_candidates = 0
    for row in evidence:
        raw_candidates = max(
            raw_candidates,
            int((row.evidence_json or {}).get("raw_candidate_cells") or 0),
        )
    valid_basins = sum(
        1
        for decision in selection.decisions
        if decision.decision_stage in {"selection", "spatial_selection"}
    )
    return [
        {"metric": "raw_candidates", "count": raw_candidates},
        {"metric": "thinned_candidates", "count": len(candidates)},
        {
            "metric": "delineated_basins",
            "count": sum(1 for catchment in delineated if catchment.status == "delineated"),
        },
        {"metric": "valid_basins", "count": valid_basins},
        {"metric": "selected_basins", "count": len(selection.selected)},
    ]


def _read_raster_frame(path: Path) -> tuple[str | None, tuple[float, ...] | None]:
    """Read a DEM CRS and bounds when the path points to a real raster."""

    try:
        with rasterio.open(path) as src:
            return crs_text(src.crs), tuple(src.bounds)
    except Exception:
        return None, None


def _default_crs(
    config: SiteSelectionConfig,
    dem_path: Path,
    dem_bounds: tuple[float, ...] | None,
) -> str | None:
    """Return the territory default CRS for a DEM that declares none.

    The default is Lambert-93 in France. It holds only when the DEM, and a
    ``bbox`` territory written in the project CRS, lie in the EPSG:2154 area
    of use, so a box outside it is refused.
    """

    crs = default_project_crs(config.territory)
    if crs is None:
        return None
    fix = "Pass crs_project to the build, or give it a DEM that carries its CRS."
    if dem_bounds is not None:
        require_lambert93_extent(dem_bounds, what=f"the DEM {dem_path}", fix=fix)
    if config.territory.mode == "bbox":
        require_lambert93_extent(
            config.territory.bbox, what="site_selection.territory.bbox", fix=fix
        )
    return crs


__all__ = [
    "DEM_AREA_LIGHT_SNAP_DIST_M",
    "SiteSelectionBuildResult",
    "build_site_selection_from_dem_area_light",
    "build_site_selection_from_generated_network",
    "build_site_selection_from_point_records",
    "select_catchments_and_write_outputs",
]
