"""The literal value types of the site selection tables, with the text of each value.

Every table file reads them, so they sit in a module of their own.
"""

from __future__ import annotations

from typing import Literal

__all__ = [
    "CandidateMode",
    "CriterionMode",
    "InfluenceType",
    "MapContextLayerRole",
    "ObservationRole",
    "OutletSnapStrategy",
    "ReferenceNetworkSource",
    "RouteOverlapMode",
    "SelectionPrinciple",
    "SpatialQuotaMode",
    "StationInfluenceUnknownPolicy",
    "StrategyProfile",
    "WorkflowInputMode",
]


SelectionPrinciple = Literal["observation_led", "criteria_crossing"]
StrategyProfile = Literal[
    "area_only",
    "gauged_downstream_station",
]
CriterionMode = Literal["hard_reject", "warning", "score", "stratify", "report_only"]
ObservationRole = Literal["primary", "bonus", "score", "stratify", "report_only", "ignore"]
CandidateMode = Literal[
    "network_sampling",
    "station_outlets",
]
OutletSnapStrategy = Literal["dem_accumulation", "bdtopage_then_dem"]
ReferenceNetworkSource = Literal["bdtopage", "custom"]
RouteOverlapMode = Literal["hard_reject", "warning", "score", "report_only"]
SpatialQuotaMode = Literal["none", "grid"]
WorkflowInputMode = Literal[
    "plan_only",
    "hydrometry",
    "delineated_catchments",
    "generated_candidates",
    "dem_area_light",
]
MapContextLayerRole = Literal["territory", "hydrography", "geology", "other"]
InfluenceType = Literal[
    "major_dam_upstream",
    "major_withdrawal_upstream",
    "major_regulated_reach",
]
StationInfluenceUnknownPolicy = Literal["neutral", "warning"]

CANDIDATE_MODE_VALUE_DOCS = {
    "network_sampling": "Generates candidate outlets by sampling the DEM-derived stream network.",
    "station_outlets": (
        "Uses imported observation station locations, such as flow stations, as candidate outlets."
    ),
}


def criterion_mode_value_docs(subject: str, *, score_hint: str) -> dict[str, str]:
    """Build value_docs for a fully-implemented CriterionMode field.

    ``subject`` names the evidence checked (for example 'basin area'). Used for
    modes whose evaluator implements all five branches with real effect.
    """

    return {
        "hard_reject": f"Rejects candidates that fail the configured {subject} check.",
        "warning": (
            f"Flags candidates that fail the configured {subject} check, without rejecting them."
        ),
        "score": f"Scores candidates by {score_hint}.",
        "stratify": f"Makes {subject} available for grouping candidates into strata.",
        "report_only": (
            f"Records {subject} evidence without any automatic accept or reject decision."
        ),
    }


OBSERVATION_ROLE_VALUE_DOCS = {
    "primary": "Accepted and recorded in the manifest; no code reads it, so a run is unchanged.",
    "bonus": "Accepted and recorded in the manifest; no code reads it, so a run is unchanged.",
    "score": "Accepted and recorded in the manifest; no code reads it, so a run is unchanged.",
    "stratify": "Accepted and recorded in the manifest; no code reads it, so a run is unchanged.",
    "report_only": ("Recorded but never read; one of the two values profile='area_only' accepts."),
    "ignore": "Recorded but never read; the other value profile='area_only' accepts.",
}
