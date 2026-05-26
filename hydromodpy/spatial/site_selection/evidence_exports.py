"""Shared evidence export helpers for site-selection runs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from hydromodpy.spatial.site_selection.config import OutputConfig
from hydromodpy.spatial.site_selection.context_evidence import (
    GeologyEvidence,
    write_geology_evidence_geojson,
    write_geology_evidence_geopackage,
    write_geology_evidence_geoparquet,
)
from hydromodpy.spatial.site_selection.decisions import (
    evidence_records_from_site_selection_evidence,
    write_evidence_records_jsonl,
)
from hydromodpy.spatial.site_selection.exports import GPKG_NAME
from hydromodpy.spatial.site_selection.exports_geojson import (
    write_observation_points_geojson,
)
from hydromodpy.spatial.site_selection.exports_geospatial import (
    write_observation_points_geopackage,
    write_observation_points_geoparquet,
)
from hydromodpy.spatial.site_selection.exports_tabular import write_jsonl
from hydromodpy.spatial.site_selection.influence import (
    InfluenceEvidence,
    write_influence_evidence_geojson,
    write_influence_evidence_geopackage,
    write_influence_evidence_geoparquet,
)
from hydromodpy.spatial.site_selection.types import ObservationEvidence


def write_site_selection_evidence_outputs(
    root: str | Path,
    *,
    selection_id: str,
    output: OutputConfig,
    output_paths: Mapping[str, Path] | None = None,
    observation_evidence: Iterable[ObservationEvidence] = (),
    piezometer_evidence: Iterable[ObservationEvidence] = (),
    influence_evidence: Iterable[InfluenceEvidence] = (),
    geology_evidence: Iterable[GeologyEvidence] = (),
    write_observation_vectors: bool = True,
    write_context_vectors: bool = True,
) -> dict[str, Path]:
    """Write specialized and normalized evidence artifacts.

    ``observation_evidence`` is the complete observation table. The optional
    ``piezometer_evidence`` subset is written separately for compatibility with
    existing artifact names.
    """

    destination_root = Path(root)
    paths = dict(output_paths or {})
    observations = list(observation_evidence)
    piezometers = list(piezometer_evidence)
    influences = list(influence_evidence)
    geologies = list(geology_evidence)

    _write_observation_evidence(
        destination_root,
        output=output,
        paths=paths,
        observation_evidence=observations,
        piezometer_evidence=piezometers,
        write_vectors=write_observation_vectors,
    )
    _write_influence_evidence(
        destination_root,
        output=output,
        paths=paths,
        evidence=influences,
        write_vectors=write_context_vectors,
    )
    _write_geology_evidence(
        destination_root,
        output=output,
        paths=paths,
        evidence=geologies,
        write_vectors=write_context_vectors,
    )
    _write_normalized_evidence(
        destination_root,
        selection_id=selection_id,
        paths=paths,
        observation_evidence=observations,
        influence_evidence=influences,
        geology_evidence=geologies,
    )
    return paths


def _write_observation_evidence(
    root: Path,
    *,
    output: OutputConfig,
    paths: dict[str, Path],
    observation_evidence: list[ObservationEvidence],
    piezometer_evidence: list[ObservationEvidence],
    write_vectors: bool,
) -> None:
    if observation_evidence:
        paths["observation_evidence_jsonl"] = write_jsonl(
            root / "observation_evidence.jsonl",
            [evidence.to_record() for evidence in observation_evidence],
        )
        if write_vectors and output.write_geojson:
            paths["observation_points_geojson"] = write_observation_points_geojson(
                root / "observation_points.geojson",
                observation_evidence,
            )
        if write_vectors and output.write_geopackage:
            gpkg_path = write_observation_points_geopackage(
                paths.get("site_selection_gpkg", root / GPKG_NAME),
                observation_evidence,
            )
            if gpkg_path is not None:
                paths["site_selection_gpkg"] = gpkg_path
        if write_vectors and output.write_geoparquet:
            geoparquet_path = write_observation_points_geoparquet(
                root / "observation_points.parquet",
                observation_evidence,
            )
            if geoparquet_path is not None:
                paths["observation_points_geoparquet"] = geoparquet_path
    if piezometer_evidence:
        paths["piezometer_evidence_jsonl"] = write_jsonl(
            root / "piezometer_evidence.jsonl",
            [evidence.to_record() for evidence in piezometer_evidence],
        )


def _write_influence_evidence(
    root: Path,
    *,
    output: OutputConfig,
    paths: dict[str, Path],
    evidence: list[InfluenceEvidence],
    write_vectors: bool,
) -> None:
    if not evidence:
        return
    paths["influence_evidence_jsonl"] = write_jsonl(
        root / "influence_evidence.jsonl",
        [item.to_record() for item in evidence],
    )
    if write_vectors and output.write_geojson:
        geojson_path = write_influence_evidence_geojson(
            root / "influence_features.geojson",
            evidence,
        )
        if geojson_path is not None:
            paths["influence_features_geojson"] = geojson_path
    if write_vectors and output.write_geopackage:
        gpkg_path = write_influence_evidence_geopackage(
            paths.get("site_selection_gpkg", root / GPKG_NAME),
            evidence,
        )
        if gpkg_path is not None:
            paths["site_selection_gpkg"] = gpkg_path
    if write_vectors and output.write_geoparquet:
        geoparquet_path = write_influence_evidence_geoparquet(
            root / "influence_features.parquet",
            evidence,
        )
        if geoparquet_path is not None:
            paths["influence_features_geoparquet"] = geoparquet_path


def _write_geology_evidence(
    root: Path,
    *,
    output: OutputConfig,
    paths: dict[str, Path],
    evidence: list[GeologyEvidence],
    write_vectors: bool,
) -> None:
    if not evidence:
        return
    paths["geology_evidence_jsonl"] = write_jsonl(
        root / "geology_evidence.jsonl",
        [item.to_record() for item in evidence],
    )
    if write_vectors and output.write_geojson:
        geojson_path = write_geology_evidence_geojson(
            root / "geology_basins.geojson",
            evidence,
        )
        if geojson_path is not None:
            paths["geology_basins_geojson"] = geojson_path
    if write_vectors and output.write_geopackage:
        gpkg_path = write_geology_evidence_geopackage(
            paths.get("site_selection_gpkg", root / GPKG_NAME),
            evidence,
        )
        if gpkg_path is not None:
            paths["site_selection_gpkg"] = gpkg_path
    if write_vectors and output.write_geoparquet:
        geoparquet_path = write_geology_evidence_geoparquet(
            root / "geology_basins.parquet",
            evidence,
        )
        if geoparquet_path is not None:
            paths["geology_basins_geoparquet"] = geoparquet_path


def _write_normalized_evidence(
    root: Path,
    *,
    selection_id: str,
    paths: dict[str, Path],
    observation_evidence: list[ObservationEvidence],
    influence_evidence: list[InfluenceEvidence],
    geology_evidence: list[GeologyEvidence],
) -> None:
    records = evidence_records_from_site_selection_evidence(
        run_id=selection_id,
        observation_evidence=observation_evidence,
        influence_evidence=influence_evidence,
        geology_evidence=geology_evidence,
    )
    if not records:
        return
    paths["site_selection_evidence_jsonl"] = write_evidence_records_jsonl(
        root / "site_selection_evidence.jsonl",
        records,
    )


__all__ = ["write_site_selection_evidence_outputs"]
