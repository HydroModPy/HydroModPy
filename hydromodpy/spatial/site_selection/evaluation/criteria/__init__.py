"""Public criterion evaluation facade for site selection."""

from __future__ import annotations

from hydromodpy.spatial.site_selection.evaluation.criteria.area import evaluate_area_criterion
from hydromodpy.spatial.site_selection.evaluation.criteria.common import CriteriaComponent
from hydromodpy.spatial.site_selection.evaluation.criteria.geology import evaluate_geology_criterion
from hydromodpy.spatial.site_selection.evaluation.criteria.influence import (
    evaluate_influence_criterion,
)
from hydromodpy.spatial.site_selection.evaluation.criteria.observations import (
    evaluate_flow_station_criterion,
    evaluate_piezometer_criterion,
    evaluate_station_influence_criterion,
)

__all__ = [
    "CriteriaComponent",
    "evaluate_area_criterion",
    "evaluate_flow_station_criterion",
    "evaluate_geology_criterion",
    "evaluate_influence_criterion",
    "evaluate_piezometer_criterion",
    "evaluate_station_influence_criterion",
]
