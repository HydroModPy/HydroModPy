"""The ``[site_selection.criteria]`` tables, one per criterion family, and their layers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, ClassVar

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.spatial.site_selection.config.value_types import (
    CriterionMode,
    InfluenceType,
    StationInfluenceUnknownPolicy,
    criterion_mode_value_docs,
)

__all__ = [
    "AreaCriteriaConfig",
    "AreaRangeConfig",
    "CriteriaConfig",
    "FlowStationCriteriaConfig",
    "GeologyCriteriaConfig",
    "GeologyLayerConfig",
    "InfluenceCriteriaConfig",
    "InfluenceLayerConfig",
    "ObservationsCriteriaConfig",
    "PiezometerLayerConfig",
    "StationInfluenceCriteriaConfig",
]


class AreaRangeConfig(HydroModelBase):
    """Readable basin-area interval used by selection criteria."""

    range_id: Annotated[str, Profile.USER] = Field(
        default="",
        description="Stable identifier for the area range.",
    )
    label: Annotated[str, Profile.USER] = Field(
        default="",
        description="Label of the area range shown in the report and the CSV outputs.",
    )
    min_area_km2: Annotated[float, Profile.USER] = Field(
        ...,
        gt=0,
        description="Smallest basin area of this range, in km2.",
        examples=[10.0],
    )
    max_area_km2: Annotated[float, Profile.USER] = Field(
        ...,
        gt=0,
        description="Largest basin area of this range, in km2.",
        examples=[50.0],
    )

    @model_validator(mode="after")
    def _validate_range(self) -> AreaRangeConfig:
        if self.min_area_km2 > self.max_area_km2:
            raise ValueError("min_area_km2 must be <= max_area_km2.")
        return self


class AreaCriteriaConfig(HydroModelBase):
    """Area criterion configuration."""

    mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description="How basin area contributes to selection.",
        json_schema_extra={
            "value_docs": criterion_mode_value_docs(
                "basin area",
                score_hint="closeness of their area to preferred_area_km2",
            )
        },
    )
    target_area_km2: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description="Named target area used for reporting or strict area profiles.",
    )
    preferred_area_km2: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description="Preferred area used by score-based campaigns.",
    )
    score_half_width_fraction: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Half-width of the area score, as a share of preferred_area_km2. The score "
            "is 1 at the preferred area and falls to 0 at that distance from it. "
            "Required by mode = 'score'."
        ),
        json_schema_extra={"unit": "-"},
    )
    hard_min_area_km2: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description="Hard lower area bound when configured.",
    )
    hard_max_area_km2: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description="Hard upper area bound when configured.",
    )
    ranges: Annotated[list[AreaRangeConfig], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Explicit area ranges used for hard rejection, warnings or "
            "stratification. Prefer this over target/preferred area fields "
            "when the campaign is defined by minimum and maximum basin sizes."
        ),
    )

    @model_validator(mode="after")
    def _validate_area(self) -> AreaCriteriaConfig:
        if (
            self.hard_min_area_km2 is not None
            and self.hard_max_area_km2 is not None
            and self.hard_min_area_km2 > self.hard_max_area_km2
        ):
            raise ValueError("hard_min_area_km2 must be <= hard_max_area_km2.")
        if self.mode == "score" and self.preferred_area_km2 is None:
            raise ValueError("area mode='score' requires preferred_area_km2.")
        if self.mode == "score" and self.score_half_width_fraction is None:
            raise ValueError("area mode='score' requires score_half_width_fraction.")
        if (
            self.mode == "hard_reject"
            and not self.ranges
            and self.hard_min_area_km2 is None
            and self.hard_max_area_km2 is None
        ):
            raise ValueError(
                "area mode='hard_reject' requires at least one area range or a hard min/max area."
            )
        return self


class FlowStationCriteriaConfig(HydroModelBase):
    """Criteria applied to flow stations in observation-led selections."""

    mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description=(
            "What the flow-station checks do to a candidate: reject it, warn, score it, "
            "group it, or only report."
        ),
        json_schema_extra={
            "value_docs": criterion_mode_value_docs(
                "flow-station",
                score_hint="record length and station-to-outlet distance",
            )
        },
    )
    min_record_years: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Shortest discharge record, in years, a station must hold. A record given as "
            "a count of daily values is divided by 365.25. Unset, record length is not checked."
        ),
        json_schema_extra={"unit": "year"},
    )
    max_station_to_outlet_distance_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Largest distance, in km, between the station and the candidate outlet. "
            "Unset, the distance is not checked."
        ),
    )
    require_station_inside_or_at_outlet: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Fail the check when the station is flagged outside the basin and away from its outlet."
        ),
    )


class StationInfluenceCriteriaConfig(HydroModelBase):
    """Criteria applied to station influence metadata."""

    mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description=(
            "What a station flagged as influenced (a dam, a withdrawal) does to its "
            "candidate: reject it, warn, score it, group it, or only report."
        ),
        json_schema_extra={
            "value_docs": criterion_mode_value_docs(
                "station-influence",
                score_hint="influence status: 1.0 if none, 0.5 if unknown, 0.0 if influenced",
            )
        },
    )
    source: Annotated[str, Profile.USER] = Field(
        default="hubeau_station_metadata",
        description=(
            "Name of the metadata source written into the station-influence evidence. "
            "It is a label and selects no provider."
        ),
    )
    warn_if_general_influence: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Raise an issue when the station metadata reports a general hydrologic "
            "influence. Under mode = 'hard_reject' the issue rejects the candidate."
        ),
    )
    warn_if_local_influence: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Raise an issue when the station metadata reports a local hydrologic "
            "influence. Under mode = 'hard_reject' the issue rejects the candidate."
        ),
    )
    warn_if_comment_keyword: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Report comment keyword matches as warnings. Comment keywords are "
            "not treated as hard-reject evidence."
        ),
    )
    unknown_policy: Annotated[StationInfluenceUnknownPolicy, Profile.USER] = Field(
        default="neutral",
        description="What a station with missing or unknown influence metadata raises.",
        json_schema_extra={
            "value_docs": {
                "neutral": (
                    "Does not raise a warning when station influence metadata is missing "
                    "or unknown."
                ),
                "warning": (
                    "Raises a warning when station influence metadata is missing or unknown."
                ),
            }
        },
    )
    comment_keywords: Annotated[list[str], Profile.USER] = Field(
        default_factory=lambda: [
            "barrage",
            "retenue",
            "derivation",
            "canal",
            "ecluse",
            "ouvrage",
            "regulation",
            "turbinage",
            "hydroelectrique",
            "usine",
        ],
        description="Keywords searched in station influence comments.",
    )


class PiezometerLayerConfig(HydroModelBase):
    """Vector layer used to compute piezometer evidence."""

    name: Annotated[str, Profile.USER] = Field(
        ...,
        min_length=1,
        description="Name of the piezometer layer, written into the evidence of each match.",
        examples=["ades_piezometers"],
    )
    path: Annotated[Path, Profile.USER] = Field(
        ...,
        description="Vector file of the piezometer points matched against each basin.",
        examples=["piezometers.gpkg"],
    )
    id_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Attribute column that names each piezometer. Unset, the row number is used.",
    )
    label_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Attribute column that labels each piezometer in the evidence. Unset, the "
            "identifier is used."
        ),
    )
    record_years_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional field containing available record length in years.",
    )
    quality_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional field containing a quality/status label.",
    )


class ObservationsCriteriaConfig(HydroModelBase):
    """Criteria applied to observation families."""

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "flow_station_mode": (
            "it did the job of flow_station.mode. Write mode under "
            "[site_selection.criteria.observations.flow_station]."
        ),
        "flow_station_max_distance_km": (
            "it did the job of flow_station.max_station_to_outlet_distance_km. Write "
            "max_station_to_outlet_distance_km under "
            "[site_selection.criteria.observations.flow_station]."
        ),
    }

    piezometer_mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description=(
            "What the piezometer checks do to a candidate: reject it, warn, score it, "
            "group it, or only report."
        ),
        json_schema_extra={
            "value_docs": criterion_mode_value_docs(
                "piezometer",
                score_hint="distance to the nearest piezometer, or piezometer count",
            )
        },
    )
    piezometer_max_distance_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Largest distance, in km, from the basin to its nearest piezometer. Under "
            "mode = 'score' the score falls from 1 at the basin to 0 at this distance."
        ),
    )
    flow_station: Annotated[FlowStationCriteriaConfig, Profile.USER] = Field(
        default_factory=FlowStationCriteriaConfig,
    )
    station_influence: Annotated[StationInfluenceCriteriaConfig, Profile.USER] = Field(
        default_factory=StationInfluenceCriteriaConfig,
    )
    piezometer_layers: Annotated[list[PiezometerLayerConfig], Profile.USER] = Field(
        default_factory=list,
        description="Optional vector layers used to compute piezometer evidence.",
    )


class InfluenceLayerConfig(HydroModelBase):
    """Vector layer used to compute anthropic-influence evidence."""

    name: Annotated[str, Profile.USER] = Field(
        ...,
        min_length=1,
        description="Name of the influence layer, written into the evidence of each match.",
        examples=["dams"],
    )
    path: Annotated[Path, Profile.USER] = Field(
        ...,
        description=(
            "Vector file of the influence features (dams, withdrawals, regulated reaches) "
            "matched against each basin."
        ),
        examples=["dams.gpkg"],
    )
    influence_type: Annotated[InfluenceType, Profile.USER] = Field(
        ...,
        description="Normalized influence flag filled when features match a basin.",
        examples=["major_dam_upstream"],
        json_schema_extra={
            "value_docs": {
                "major_dam_upstream": (
                    "Marks matching basins as having a major dam upstream of the outlet."
                ),
                "major_withdrawal_upstream": (
                    "Marks matching basins as having a major water withdrawal upstream."
                ),
                "major_regulated_reach": (
                    "Marks matching basins as having a major regulated reach upstream."
                ),
            }
        },
    )
    id_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Attribute column that names each feature. Unset, the row number is used.",
    )
    label_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Attribute column that labels each feature in the evidence. Unset, the "
            "identifier is used."
        ),
    )
    severity_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional field used to classify major features.",
    )
    major_values: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Values considered major in severity_field. When empty, every "
            "matched feature is considered major."
        ),
    )


class InfluenceCriteriaConfig(HydroModelBase):
    """Known-influence checks for observation-led campaigns."""

    mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description=(
            "What a basin carrying an influence flag selected by the reject_* keys does "
            "to its candidate: reject it, warn, or only report."
        ),
        json_schema_extra={
            "value_docs": {
                "hard_reject": (
                    "Rejects a candidate when a configured influence rejection flag is present."
                ),
                "warning": (
                    "Flags a configured influence flag as a warning without rejecting "
                    "the candidate."
                ),
                "score": ("Behaves like warning here: flags influence without computing a score."),
                "stratify": (
                    "Behaves like warning here: flags influence without grouping by class."
                ),
                "report_only": (
                    "Records influence evidence without any automatic accept or reject decision."
                ),
            }
        },
    )
    reject_major_dam_upstream: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Count a major dam upstream of the outlet as a failure of the influence check. "
            "What a failure does follows mode."
        ),
    )
    reject_major_withdrawal_upstream: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Count a major water withdrawal upstream of the outlet as a failure of the "
            "influence check. What a failure does follows mode."
        ),
    )
    reject_major_regulated_reach: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Count a major regulated reach upstream of the outlet as a failure of the "
            "influence check. What a failure does follows mode."
        ),
    )
    influence_search_radius_km: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Radius, in km, of the disk around the outlet searched for influence features "
            "when a candidate has no basin polygon. Unset, such a candidate gets no evidence."
        ),
    )
    layers: Annotated[list[InfluenceLayerConfig], Profile.USER] = Field(
        default_factory=list,
        description="Optional vector layers used to compute influence flags automatically.",
    )


class GeologyLayerConfig(HydroModelBase):
    """Polygon layer used to compute basin geology classes."""

    name: Annotated[str, Profile.USER] = Field(
        ...,
        min_length=1,
        description="Name of the geology layer, written into the evidence of each match.",
        examples=["brgm_1m"],
    )
    path: Annotated[Path, Profile.USER] = Field(
        ...,
        description="Vector polygon file containing geology units.",
        examples=["geology.gpkg"],
    )
    class_field: Annotated[str, Profile.USER] = Field(
        ...,
        min_length=1,
        description="Feature field containing the geology class.",
        examples=["lithology"],
    )
    id_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Attribute column that names each polygon. Unset, the row number is used.",
    )
    label_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Attribute column that labels each polygon in the evidence.",
    )


class GeologyCriteriaConfig(HydroModelBase):
    """Geology criterion configuration."""

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "prefer_diversity": (
            "no step read it, so the selection was the same either way. To group the "
            "candidates by geology class, write geology.mode = 'stratify'."
        ),
    }

    mode: Annotated[CriterionMode, Profile.USER] = Field(
        default="report_only",
        description=(
            "What the geology class of a basin does to its candidate: score it, group "
            "it, or only report. Geology cannot reject or warn today."
        ),
        json_schema_extra={
            "value_docs": {
                "hard_reject": (
                    "Behaves like report_only here: geology cannot yet reject a candidate."
                ),
                "warning": ("Behaves like report_only here: geology cannot yet raise a warning."),
                "score": "Gives a full score when a geology class is found, none otherwise.",
                "stratify": (
                    "Makes the geology class available for grouping candidates into strata."
                ),
                "report_only": (
                    "Records geology evidence without any automatic accept or reject decision."
                ),
            }
        },
    )
    layers: Annotated[list[GeologyLayerConfig], Profile.USER] = Field(
        default_factory=list,
        description="Optional polygon layers used to compute geology evidence.",
    )


_CRITERIA_LIST_REFUSAL = (
    "the list was recorded and never decided anything: each criterion's own mode "
    "decides. Write mode under the criterion: criteria.area.mode, criteria.geology.mode, "
    "criteria.influence.mode, criteria.observations.flow_station.mode or "
    "criteria.observations.piezometer_mode."
)


class CriteriaConfig(HydroModelBase):
    """Criteria of the selection, one table per family."""

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "ruleset": "no step read the name of the criteria set. Remove the key.",
        "hard_reject": _CRITERIA_LIST_REFUSAL,
        "warning": _CRITERIA_LIST_REFUSAL,
        "soft_score": _CRITERIA_LIST_REFUSAL,
        "report_only": _CRITERIA_LIST_REFUSAL,
    }
    area: Annotated[AreaCriteriaConfig, Profile.USER] = Field(default_factory=AreaCriteriaConfig)
    observations: Annotated[ObservationsCriteriaConfig, Profile.USER] = Field(
        default_factory=ObservationsCriteriaConfig,
    )
    influence: Annotated[InfluenceCriteriaConfig, Profile.USER] = Field(
        default_factory=InfluenceCriteriaConfig,
    )
    geology: Annotated[GeologyCriteriaConfig, Profile.USER] = Field(
        default_factory=GeologyCriteriaConfig,
    )
