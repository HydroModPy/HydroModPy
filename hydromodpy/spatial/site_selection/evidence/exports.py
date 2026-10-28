"""Shared evidence export helpers for site-selection runs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from hydromodpy.spatial.site_selection.config import OutputConfig
from hydromodpy.spatial.site_selection.decisions import (
    evidence_records_from_site_selection_evidence,
    write_evidence_records_jsonl,
)
from hydromodpy.spatial.site_selection.domain.observations import ObservationEvidence
from hydromodpy.spatial.site_selection.evidence.context import GeologyEvidence
from hydromodpy.spatial.site_selection.evidence.influence import InfluenceEvidence
from hydromodpy.spatial.site_selection.outputs.evidence_layers import write_evidence_layer
from hydromodpy.spatial.site_selection.outputs.geojson import write_observation_points_geojson
from hydromodpy.spatial.site_selection.outputs.geospatial import (
    observation_points_gdf,
    write_vector_layer,
)
from hydromodpy.spatial.site_selection.outputs.tabular import write_jsonl
from hydromodpy.spatial.site_selection.outputs.writer import GPKG_NAME


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
    ``piezometer_evidence`` subset is written separately for focused review.
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
    for name, role, evidence in (
        ("influence", "influence_features", influences),
        ("geology", "geology_basins", geologies),
    ):
        _write_layer_evidence(
            destination_root,
            name=name,
            role=role,
            output=output,
            paths=paths,
            evidence=evidence,
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
            gpkg_path = write_vector_layer(
                observation_points_gdf(observation_evidence),
                paths.get("site_selection_gpkg", root / GPKG_NAME),
                fmt="gpkg",
                layer="observation_points",
            )
            if gpkg_path is not None:
                paths["site_selection_gpkg"] = gpkg_path
        if write_vectors and output.write_geoparquet:
            geoparquet_path = write_vector_layer(
                observation_points_gdf(observation_evidence),
                root / "observation_points.parquet",
                fmt="geoparquet",
            )
            if geoparquet_path is not None:
                paths["observation_points_geoparquet"] = geoparquet_path
    if piezometer_evidence:
        paths["piezometer_evidence_jsonl"] = write_jsonl(
            root / "piezometer_evidence.jsonl",
            [evidence.to_record() for evidence in piezometer_evidence],
        )


def _write_layer_evidence(
    root: Path,
    *,
    name: str,
    role: str,
    output: OutputConfig,
    paths: dict[str, Path],
    evidence: list[InfluenceEvidence] | list[GeologyEvidence],
    write_vectors: bool,
) -> None:
    if not evidence:
        return
    paths[f"{name}_evidence_jsonl"] = write_jsonl(
        root / f"{name}_evidence.jsonl",
        [item.to_record() for item in evidence],
    )
    if not write_vectors:
        return
    for enabled, fmt, path, key in (
        (output.write_geojson, "geojson", root / f"{role}.geojson", f"{role}_geojson"),
        (
            output.write_geopackage,
            "gpkg",
            paths.get("site_selection_gpkg", root / GPKG_NAME),
            "site_selection_gpkg",
        ),
        (output.write_geoparquet, "geoparquet", root / f"{role}.parquet", f"{role}_geoparquet"),
    ):
        if not enabled:
            continue
        written = write_evidence_layer(path, evidence, role=role, fmt=fmt)
        if written is not None:
            paths[key] = written


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
