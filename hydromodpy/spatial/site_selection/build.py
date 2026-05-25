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
from hydromodpy.spatial.site_selection.candidate_generation import (
    CandidateGenerationEvidence,
    candidate_generation_evidence_with_candidate_attributes,
    ensure_raw_accumulation_cells,
    generate_dem_area_light_candidate_outlets,
    generate_network_candidate_outlets,
    write_candidate_generation_jsonl,
    write_candidate_outlets_geojson,
    write_generated_network_geojson,
)
from hydromodpy.spatial.site_selection.candidate_outlets import (
    CandidateOutlet,
    candidate_outlets_from_point_records,
    thin_candidate_outlets,
)
from hydromodpy.spatial.site_selection.config import (
    AreaCriteriaConfig,
    SiteSelectionConfig,
)
from hydromodpy.spatial.site_selection.context_evidence import (
    annotate_catchments_with_geology_layers,
    annotate_catchments_with_piezometer_layers,
    write_geology_evidence_geojson,
    write_geology_evidence_geopackage,
    write_geology_evidence_geoparquet,
)
from hydromodpy.spatial.site_selection.delineation import (
    DelineatedCatchment,
    try_delineate_candidate_outlet,
)
from hydromodpy.spatial.site_selection.exports import (
    GPKG_NAME,
    write_csv,
    write_jsonl,
    write_observation_points_geojson,
    write_observation_points_geopackage,
    write_observation_points_geoparquet,
    write_selection_result,
)
from hydromodpy.spatial.site_selection.flow_products_adapter import (
    FlowProductsBuilder,
    SiteSelectionFlowProducts,
    build_site_selection_flow_products,
)
from hydromodpy.spatial.site_selection.influence import (
    annotate_catchments_with_influence_layers,
    write_influence_evidence_geojson,
    write_influence_evidence_geopackage,
    write_influence_evidence_geoparquet,
)
from hydromodpy.spatial.site_selection.observations import build_observation_evidence
from hydromodpy.spatial.site_selection.reference_network import (
    ReferenceNetworkBundle,
    load_reference_network_for_outlets,
    score_outlets_against_reference_network,
)
from hydromodpy.spatial.site_selection.selection import (
    SelectionDecision,
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
    candidate_generation_evidence: list[CandidateGenerationEvidence] | None = None


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
    reference_network, reference_bundle = _maybe_load_reference_network(
        config=config,
        candidates=candidates,
        target_crs=target_crs or _first_candidate_crs(candidates),
        root=root,
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
            reference_network=reference_network,
            reference_network_source=(
                "" if reference_bundle is None else reference_bundle.source
            ),
            reference_network_max_distance_m=config.outlets.reference_network_max_distance_m,
        )
        for candidate in candidates
    ]
    delineated, influence_evidence = annotate_catchments_with_influence_layers(
        delineated,
        config=config.criteria.influence,
    )
    delineated, geology_evidence = annotate_catchments_with_geology_layers(
        delineated,
        config=config.criteria.geology,
    )
    delineated, piezometer_evidence = annotate_catchments_with_piezometer_layers(
        delineated,
        config=config.criteria.observations,
    )
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
    observation_evidence.extend(piezometer_evidence)
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
            write_geoparquet=config.output.write_geoparquet,
            write_geopackage=config.output.write_geopackage,
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
        if config.output.write_geopackage:
            gpkg_path = write_observation_points_geopackage(
                output_paths.get("site_selection_gpkg", root / GPKG_NAME),
                observation_evidence,
            )
            if gpkg_path is not None:
                output_paths["site_selection_gpkg"] = gpkg_path
        if config.output.write_geoparquet:
            geoparquet_path = write_observation_points_geoparquet(
                root / "observation_points.parquet",
                observation_evidence,
            )
            if geoparquet_path is not None:
                output_paths["observation_points_geoparquet"] = geoparquet_path
        if piezometer_evidence:
            output_paths["piezometer_evidence_jsonl"] = write_jsonl(
                root / "piezometer_evidence.jsonl",
                [evidence.to_record() for evidence in piezometer_evidence],
            )
        if influence_evidence:
            output_paths["influence_evidence_jsonl"] = write_jsonl(
                root / "influence_evidence.jsonl",
                [evidence.to_record() for evidence in influence_evidence],
            )
            if config.output.write_geojson:
                geojson_path = write_influence_evidence_geojson(
                    root / "influence_features.geojson",
                    influence_evidence,
                )
                if geojson_path is not None:
                    output_paths["influence_features_geojson"] = geojson_path
            if config.output.write_geopackage:
                gpkg_path = write_influence_evidence_geopackage(
                    output_paths.get("site_selection_gpkg", root / GPKG_NAME),
                    influence_evidence,
                )
                if gpkg_path is not None:
                    output_paths["site_selection_gpkg"] = gpkg_path
            if config.output.write_geoparquet:
                geoparquet_path = write_influence_evidence_geoparquet(
                    root / "influence_features.parquet",
                    influence_evidence,
                )
                if geoparquet_path is not None:
                    output_paths["influence_features_geoparquet"] = geoparquet_path
        if geology_evidence:
            output_paths["geology_evidence_jsonl"] = write_jsonl(
                root / "geology_evidence.jsonl",
                [evidence.to_record() for evidence in geology_evidence],
            )
            if config.output.write_geojson:
                geojson_path = write_geology_evidence_geojson(
                    root / "geology_basins.geojson",
                    geology_evidence,
                )
                if geojson_path is not None:
                    output_paths["geology_basins_geojson"] = geojson_path
            if config.output.write_geopackage:
                gpkg_path = write_geology_evidence_geopackage(
                    output_paths.get("site_selection_gpkg", root / GPKG_NAME),
                    geology_evidence,
                )
                if gpkg_path is not None:
                    output_paths["site_selection_gpkg"] = gpkg_path
            if config.output.write_geoparquet:
                geoparquet_path = write_geology_evidence_geoparquet(
                    root / "geology_basins.parquet",
                    geology_evidence,
                )
                if geoparquet_path is not None:
                    output_paths["geology_basins_geoparquet"] = geoparquet_path
        flow_manifest = flow_products.to_manifest_record()
        flow_manifest["dem_path"] = str(dem_path)
        flow_manifest["dem_source"] = config.dem.source
        if reference_bundle is not None:
            flow_manifest["reference_network"] = reference_bundle.to_manifest_record()
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


def build_site_selection_from_generated_network(
    *,
    config: SiteSelectionConfig,
    dem_init_path: str | Path | None = None,
    output_root: str | Path | None = None,
    crs_project: str | None = None,
    backend: object | None = None,
    flow_products_builder: FlowProductsBuilder | None = None,
    delineation_builder=None,
    area_reader=None,
    write_outputs: bool = True,
) -> SiteSelectionBuildResult:
    """Run DEM/network-generated site selection without station or CSV candidates."""

    root = Path(output_root) if output_root is not None else config.output_root
    root = root.expanduser().resolve()
    dem_path = Path(dem_init_path or config.dem.path).expanduser().resolve() if (
        dem_init_path or config.dem.path
    ) else None
    if dem_path is None:
        raise ValueError("build_site_selection_from_generated_network requires dem_init_path or dem.path.")
    target_crs = crs_project or _read_raster_crs(dem_path) or _default_project_crs(config)

    flow_products = build_site_selection_flow_products(
        dem_init_path=dem_path,
        output_dir=root / "flow_products",
        hydrology=config.hydrology,
        crs_project=target_crs,
        backend=backend,
        builder=flow_products_builder or build_regional_flow_products,
    )
    candidates, candidate_generation_evidence = generate_network_candidate_outlets(
        flow_products=flow_products,
        outlets=config.outlets,
        hydrology=config.hydrology,
    )
    reference_network, reference_bundle = _maybe_load_reference_network_for_generated_candidates(
        config=config,
        candidates=candidates,
        target_crs=target_crs or _first_candidate_crs(candidates),
        root=root,
    )
    if reference_network is not None and reference_bundle is not None:
        candidates = score_outlets_against_reference_network(
            candidates,
            reference_network,
            max_distance_m=config.outlets.reference_network_max_distance_m,
            source=reference_bundle.source,
        )
        candidate_generation_evidence = (
            candidate_generation_evidence_with_candidate_attributes(
                candidate_generation_evidence,
                candidates,
            )
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
            reference_network=(
                reference_network
                if config.outlets.snap_strategy == "bdtopage_then_dem"
                else None
            ),
            reference_network_source=(
                "" if reference_bundle is None else reference_bundle.source
            ),
            reference_network_max_distance_m=config.outlets.reference_network_max_distance_m,
        )
        for candidate in candidates
    ]
    delineated, influence_evidence = annotate_catchments_with_influence_layers(
        delineated,
        config=config.criteria.influence,
    )
    delineated, geology_evidence = annotate_catchments_with_geology_layers(
        delineated,
        config=config.criteria.geology,
    )
    delineated, piezometer_evidence = annotate_catchments_with_piezometer_layers(
        delineated,
        config=config.criteria.observations,
    )
    selection = select_delineated_catchments(
        delineated,
        criteria=config.criteria,
        spatial_selection=config.spatial_selection,
        selection_principle=config.strategy.principle,
    )
    observation_evidence = list(piezometer_evidence)
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
            write_geoparquet=config.output.write_geoparquet,
            write_geopackage=config.output.write_geopackage,
        )
        output_paths["candidate_generation_jsonl"] = write_candidate_generation_jsonl(
            root / "candidate_generation.jsonl",
            candidate_generation_evidence,
        )
        if config.output.write_geojson:
            output_paths["candidate_outlets_geojson"] = write_candidate_outlets_geojson(
                root / "candidate_outlets.geojson",
                candidates,
            )
            output_paths["generated_network_geojson"] = write_generated_network_geojson(
                root / "generated_dem_network.geojson",
                flow_products=flow_products,
                hydrology=config.hydrology,
                max_cells=config.outlets.max_generated_network_cells,
            )
        if observation_evidence:
            output_paths["observation_evidence_jsonl"] = _write_observation_evidence_jsonl(
                root / "observation_evidence.jsonl",
                observation_evidence,
            )
            if config.output.write_geojson:
                output_paths["observation_points_geojson"] = write_observation_points_geojson(
                    root / "observation_points.geojson",
                    observation_evidence,
                )
            if config.output.write_geopackage:
                gpkg_path = write_observation_points_geopackage(
                    output_paths.get("site_selection_gpkg", root / GPKG_NAME),
                    observation_evidence,
                )
                if gpkg_path is not None:
                    output_paths["site_selection_gpkg"] = gpkg_path
            if config.output.write_geoparquet:
                geoparquet_path = write_observation_points_geoparquet(
                    root / "observation_points.parquet",
                    observation_evidence,
                )
                if geoparquet_path is not None:
                    output_paths["observation_points_geoparquet"] = geoparquet_path
        if piezometer_evidence:
            output_paths["piezometer_evidence_jsonl"] = write_jsonl(
                root / "piezometer_evidence.jsonl",
                [evidence.to_record() for evidence in piezometer_evidence],
            )
        if influence_evidence:
            output_paths["influence_evidence_jsonl"] = write_jsonl(
                root / "influence_evidence.jsonl",
                [evidence.to_record() for evidence in influence_evidence],
            )
            if config.output.write_geojson:
                geojson_path = write_influence_evidence_geojson(
                    root / "influence_features.geojson",
                    influence_evidence,
                )
                if geojson_path is not None:
                    output_paths["influence_features_geojson"] = geojson_path
            if config.output.write_geopackage:
                gpkg_path = write_influence_evidence_geopackage(
                    output_paths.get("site_selection_gpkg", root / GPKG_NAME),
                    influence_evidence,
                )
                if gpkg_path is not None:
                    output_paths["site_selection_gpkg"] = gpkg_path
            if config.output.write_geoparquet:
                geoparquet_path = write_influence_evidence_geoparquet(
                    root / "influence_features.parquet",
                    influence_evidence,
                )
                if geoparquet_path is not None:
                    output_paths["influence_features_geoparquet"] = geoparquet_path
        if geology_evidence:
            output_paths["geology_evidence_jsonl"] = write_jsonl(
                root / "geology_evidence.jsonl",
                [evidence.to_record() for evidence in geology_evidence],
            )
            if config.output.write_geojson:
                geojson_path = write_geology_evidence_geojson(
                    root / "geology_basins.geojson",
                    geology_evidence,
                )
                if geojson_path is not None:
                    output_paths["geology_basins_geojson"] = geojson_path
            if config.output.write_geopackage:
                gpkg_path = write_geology_evidence_geopackage(
                    output_paths.get("site_selection_gpkg", root / GPKG_NAME),
                    geology_evidence,
                )
                if gpkg_path is not None:
                    output_paths["site_selection_gpkg"] = gpkg_path
            if config.output.write_geoparquet:
                geoparquet_path = write_geology_evidence_geoparquet(
                    root / "geology_basins.parquet",
                    geology_evidence,
                )
                if geoparquet_path is not None:
                    output_paths["geology_basins_geoparquet"] = geoparquet_path
        flow_manifest = flow_products.to_manifest_record()
        flow_manifest["dem_path"] = str(dem_path)
        flow_manifest["dem_source"] = config.dem.source
        if reference_bundle is not None:
            flow_manifest["reference_network"] = reference_bundle.to_manifest_record()
        output_paths.update(
            write_manifest_and_optional_report(
                config=config.model_copy(update={"output_root": root}),
                selection=selection,
                output_paths=output_paths,
                action="generated_candidates",
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
        candidate_generation_evidence=candidate_generation_evidence,
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
) -> SiteSelectionBuildResult:
    """Run the lightweight DEM-only basin-area selection workflow."""

    if config.dem_area_light is None:
        raise ValueError("build_site_selection_from_dem_area_light requires dem_area_light config.")

    root = Path(output_root) if output_root is not None else config.output_root
    root = root.expanduser().resolve()
    dem_path = Path(dem_init_path or config.dem.path).expanduser().resolve() if (
        dem_init_path or config.dem.path
    ) else None
    if dem_path is None:
        raise ValueError("build_site_selection_from_dem_area_light requires dem_init_path or dem.path.")
    target_crs = crs_project or _read_raster_crs(dem_path) or _default_project_crs(config)

    flow_products = build_site_selection_flow_products(
        dem_init_path=dem_path,
        output_dir=root / "flow_products",
        hydrology=config.hydrology,
        crs_project=target_crs,
        backend=backend,
        builder=flow_products_builder or build_regional_flow_products,
    )
    raw_accumulation_path = (
        Path(
            raw_accumulation_builder(
                flow_products=flow_products,
                output_dir=root / "flow_products",
                backend=backend,
                crs_project=target_crs,
            )
        )
        if raw_accumulation_builder is not None
        else ensure_raw_accumulation_cells(
            flow_products=flow_products,
            output_dir=root / "flow_products",
            backend=backend,
            crs_project=target_crs,
        )
    )
    candidates, candidate_generation_evidence = generate_dem_area_light_candidate_outlets(
        flow_products=flow_products,
        dem_area_light=config.dem_area_light,
        hydrology=config.hydrology,
        accumulation_cells_path=raw_accumulation_path,
        max_candidates_before_delineation=config.dem_area_light.max_candidates_before_delineation,
    )
    delineated = [
        try_delineate_candidate_outlet(
            outlet=candidate,
            flow_products=flow_products,
            output_root=root / "catchments",
            snap_dist_m=1,
            crs_project=target_crs or candidate.crs,
            site_id=candidate.candidate_id,
            backend=backend,
            builder=delineation_builder or _default_delineation_builder,
            area_reader=area_reader,
        )
        for candidate in candidates
    ]
    delineated, influence_evidence = annotate_catchments_with_influence_layers(
        delineated,
        config=config.criteria.influence,
    )
    delineated, geology_evidence = annotate_catchments_with_geology_layers(
        delineated,
        config=config.criteria.geology,
    )
    delineated, piezometer_evidence = annotate_catchments_with_piezometer_layers(
        delineated,
        config=config.criteria.observations,
    )
    criteria = _dem_area_light_criteria(config)
    selection = select_delineated_catchments(
        delineated,
        criteria=criteria,
        spatial_selection=_dem_area_light_spatial_selection(config),
        selection_principle=config.strategy.principle,
        basin_geometries=_load_basin_geometries(delineated),
    )
    selection = _limit_selection_result(selection, max_selected=config.dem_area_light.n_basins)
    observation_evidence = list(piezometer_evidence)
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
            write_geoparquet=config.output.write_geoparquet,
            write_geopackage=config.output.write_geopackage,
        )
        output_paths["candidate_generation_jsonl"] = write_candidate_generation_jsonl(
            root / "candidate_generation.jsonl",
            candidate_generation_evidence,
        )
        output_paths["diagnostics_csv"] = write_csv(
            root / "diagnostics.csv",
            _dem_area_light_diagnostic_rows(
                candidates=candidates,
                evidence=candidate_generation_evidence,
                delineated=delineated,
                selection=selection,
            ),
            fieldnames=["metric", "count"],
        )
        if config.output.write_geojson:
            output_paths["candidate_outlets_geojson"] = write_candidate_outlets_geojson(
                root / "candidate_outlets.geojson",
                candidates,
            )
            output_paths["generated_network_geojson"] = write_generated_network_geojson(
                root / "generated_dem_network.geojson",
                flow_products=flow_products,
                hydrology=config.hydrology,
                max_cells=config.outlets.max_generated_network_cells,
            )
        if observation_evidence:
            output_paths["observation_evidence_jsonl"] = _write_observation_evidence_jsonl(
                root / "observation_evidence.jsonl",
                observation_evidence,
            )
        if piezometer_evidence:
            output_paths["piezometer_evidence_jsonl"] = write_jsonl(
                root / "piezometer_evidence.jsonl",
                [evidence.to_record() for evidence in piezometer_evidence],
            )
        if influence_evidence:
            output_paths["influence_evidence_jsonl"] = write_jsonl(
                root / "influence_evidence.jsonl",
                [evidence.to_record() for evidence in influence_evidence],
            )
        if geology_evidence:
            output_paths["geology_evidence_jsonl"] = write_jsonl(
                root / "geology_evidence.jsonl",
                [evidence.to_record() for evidence in geology_evidence],
            )
        flow_manifest = flow_products.to_manifest_record()
        flow_manifest["dem_path"] = str(dem_path)
        flow_manifest["dem_source"] = config.dem.source
        flow_manifest["raw_flow_accumulation_cells_path"] = str(raw_accumulation_path)
        flow_manifest["dem_area_light"] = config.dem_area_light.model_dump(mode="json")
        output_paths.update(
            write_manifest_and_optional_report(
                config=config.model_copy(update={"output_root": root}),
                selection=selection,
                output_paths=output_paths,
                action="dem_area_light",
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
        candidate_generation_evidence=candidate_generation_evidence,
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


def _maybe_load_reference_network(
    *,
    config: SiteSelectionConfig,
    candidates: list[CandidateOutlet],
    target_crs: str | None,
    root: Path,
) -> tuple[object | None, ReferenceNetworkBundle | None]:
    if config.outlets.snap_strategy != "bdtopage_then_dem":
        return None, None
    if not target_crs:
        raise ValueError("bdtopage_then_dem requires a projected outlet CRS.")
    network, bundle = load_reference_network_for_outlets(
        source=config.outlets.reference_network_source,
        path=config.outlets.reference_network_path,
        outlets=candidates,
        target_crs=target_crs,
        output_dir=root / "reference_network",
        fetch_margin_m=config.outlets.reference_network_fetch_margin_m,
        page_size=config.outlets.reference_network_page_size,
        force_refresh=config.outlets.reference_network_force_refresh,
    )
    return network, bundle


def _maybe_load_reference_network_for_generated_candidates(
    *,
    config: SiteSelectionConfig,
    candidates: list[CandidateOutlet],
    target_crs: str | None,
    root: Path,
) -> tuple[object | None, ReferenceNetworkBundle | None]:
    should_load_for_snap = config.outlets.snap_strategy == "bdtopage_then_dem"
    should_load_for_score_only = (
        config.outlets.snap_strategy == "dem_accumulation"
        and config.outlets.reference_network_path is not None
    )
    if not should_load_for_snap and not should_load_for_score_only:
        return None, None
    if not target_crs:
        raise ValueError("Reference-network scoring requires a projected outlet CRS.")
    network, bundle = load_reference_network_for_outlets(
        source=config.outlets.reference_network_source,
        path=config.outlets.reference_network_path,
        outlets=candidates,
        target_crs=target_crs,
        output_dir=root / "reference_network",
        fetch_margin_m=config.outlets.reference_network_fetch_margin_m,
        page_size=config.outlets.reference_network_page_size,
        force_refresh=config.outlets.reference_network_force_refresh,
    )
    return network, bundle


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
        }
    )


def _load_basin_geometries(catchments: list[DelineatedCatchment]) -> dict[str, object]:
    try:
        import geopandas as gpd
    except ImportError:
        return {}

    geometries: dict[str, object] = {}
    for catchment in catchments:
        if catchment.status != "delineated" or not catchment.watershed_shp:
            continue
        try:
            frame = gpd.read_file(str(catchment.watershed_shp))
        except Exception:
            continue
        if frame.empty:
            continue
        geometry = (
            frame.geometry.union_all()
            if hasattr(frame.geometry, "union_all")
            else frame.geometry.unary_union
        )
        if geometry is not None and not geometry.is_empty:
            geometries[catchment.site_id] = geometry
    return geometries


def _limit_selection_result(
    selection: SelectionResult,
    *,
    max_selected: int,
) -> SelectionResult:
    if len(selection.selected) <= int(max_selected):
        return selection

    decisions_by_id = {decision.site_id: decision for decision in selection.decisions}
    selected_order = sorted(
        selection.selected,
        key=lambda catchment: (
            -(_rank_score_for_sort(decisions_by_id, catchment.site_id)),
            catchment.site_id,
        ),
    )
    kept_ids = {catchment.site_id for catchment in selected_order[: int(max_selected)]}
    demoted = [catchment for catchment in selection.selected if catchment.site_id not in kept_ids]

    decisions: list[SelectionDecision] = []
    for decision in selection.decisions:
        if decision.selected and decision.site_id not in kept_ids:
            summary = dict(decision.criteria_summary_json)
            summary["target_count"] = "rejected"
            decisions.append(
                SelectionDecision(
                    site_id=decision.site_id,
                    selection_principle=decision.selection_principle,
                    selected=False,
                    decision_stage="selection",
                    decision_reason="target_count_reached",
                    blocking_flags=[*decision.blocking_flags, "target_count_reached"],
                    warning_flags=list(decision.warning_flags),
                    rank_score=decision.rank_score,
                    stratification_class=decision.stratification_class,
                    criteria_summary_json=summary,
                )
            )
            continue
        decisions.append(decision)

    return SelectionResult(
        selected=sorted(
            [catchment for catchment in selection.selected if catchment.site_id in kept_ids],
            key=lambda catchment: catchment.site_id,
        ),
        rejected=sorted(
            [*selection.rejected, *demoted],
            key=lambda catchment: catchment.site_id,
        ),
        decisions=sorted(decisions, key=lambda decision: decision.site_id),
        criteria_components=selection.criteria_components,
    )


def _rank_score_for_sort(
    decisions_by_id: dict[str, SelectionDecision],
    site_id: str,
) -> float:
    decision = decisions_by_id.get(site_id)
    if decision is None or decision.rank_score is None:
        return 0.0
    return float(decision.rank_score)


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


def _first_candidate_crs(candidates: list[CandidateOutlet]) -> str | None:
    for candidate in candidates:
        if candidate.crs:
            return candidate.crs
    return None


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
    "build_site_selection_from_dem_area_light",
    "build_site_selection_from_generated_network",
    "build_site_selection_from_point_records",
]
