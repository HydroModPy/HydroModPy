"""Catchment annotation phase for site-selection builds."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from hydromodpy.spatial.site_selection.config.criteria_config import CriteriaConfig
from hydromodpy.spatial.site_selection.domain.delineated_catchment import DelineatedCatchment
from hydromodpy.spatial.site_selection.domain.observation_evidence import ObservationEvidence
from hydromodpy.spatial.site_selection.evidence.geology_layers import (
    GeologyEvidence,
    annotate_catchments_with_geology_layers,
)
from hydromodpy.spatial.site_selection.evidence.influence import (
    InfluenceEvidence,
    annotate_catchments_with_influence_layers,
)
from hydromodpy.spatial.site_selection.evidence.piezometer_layers import (
    annotate_catchments_with_piezometer_layers,
)


@dataclass(frozen=True)
class CatchmentAnnotationResult:
    """Annotated catchments and the evidence generated during annotation."""

    catchments: list[DelineatedCatchment]
    influence_evidence: list[InfluenceEvidence]
    geology_evidence: list[GeologyEvidence]
    piezometer_evidence: list[ObservationEvidence]


def annotate_site_selection_catchments(
    catchments: Iterable[DelineatedCatchment],
    *,
    criteria: CriteriaConfig,
) -> CatchmentAnnotationResult:
    """Apply all configured context annotations to delineated catchments."""

    annotated, influence_evidence = annotate_catchments_with_influence_layers(
        list(catchments),
        config=criteria.influence,
    )
    annotated, geology_evidence = annotate_catchments_with_geology_layers(
        annotated,
        config=criteria.geology,
    )
    annotated, piezometer_evidence = annotate_catchments_with_piezometer_layers(
        annotated,
        config=criteria.observations,
    )
    return CatchmentAnnotationResult(
        catchments=annotated,
        influence_evidence=influence_evidence,
        geology_evidence=geology_evidence,
        piezometer_evidence=piezometer_evidence,
    )


__all__ = [
    "CatchmentAnnotationResult",
    "annotate_site_selection_catchments",
]
