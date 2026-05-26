"""Core output phase for site-selection builds."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.context_evidence import GeologyEvidence
from hydromodpy.spatial.site_selection.evidence_exports import (
    write_site_selection_evidence_outputs,
)
from hydromodpy.spatial.site_selection.exports import write_selection_result
from hydromodpy.spatial.site_selection.influence import InfluenceEvidence
from hydromodpy.spatial.site_selection.selection import SelectionResult
from hydromodpy.spatial.site_selection.types import ObservationEvidence


def write_core_site_selection_outputs(
    root: str | Path,
    *,
    config: SiteSelectionConfig,
    selection: SelectionResult,
    region_id: str = "",
    observation_evidence: Iterable[ObservationEvidence] = (),
    piezometer_evidence: Iterable[ObservationEvidence] = (),
    influence_evidence: Iterable[InfluenceEvidence] = (),
    geology_evidence: Iterable[GeologyEvidence] = (),
    write_observation_vectors: bool = True,
    write_context_vectors: bool = True,
) -> dict[str, Path]:
    """Write core selection outputs and all evidence outputs."""

    output_paths = write_selection_result(
        root,
        selection,
        selection_id=config.selection_id,
        region_id=region_id,
        write_selected=config.output.write_csv and config.output.write_selected,
        write_rejected=config.output.write_csv and config.output.write_rejected,
        write_regional_lab_csv_output=config.output.write_regional_lab_csv,
        write_geojson=config.output.write_geojson,
        write_geoparquet=config.output.write_geoparquet,
        write_geopackage=config.output.write_geopackage,
    )
    return write_site_selection_evidence_outputs(
        root,
        selection_id=config.selection_id,
        output=config.output,
        output_paths=output_paths,
        observation_evidence=observation_evidence,
        piezometer_evidence=piezometer_evidence,
        influence_evidence=influence_evidence,
        geology_evidence=geology_evidence,
        write_observation_vectors=write_observation_vectors,
        write_context_vectors=write_context_vectors,
    )


__all__ = ["write_core_site_selection_outputs"]
