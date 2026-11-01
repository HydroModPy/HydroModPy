"""The ``[site_selection.strategy]`` and ``[site_selection.territory]`` tables."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, ClassVar, Literal

from pydantic import Field, model_validator

from hydromodpy.core.administrative_france import validate_french_regions
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.site_selection.config.value_types import (
    OBSERVATION_ROLE_VALUE_DOCS,
    ObservationRole,
    SelectionPrinciple,
    StrategyProfile,
)

__all__ = [
    "StrategyConfig",
    "TerritoryConfig",
]


class StrategyConfig(HydroModelBase):
    """High-level strategy controlling candidate generation and criterion order."""

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "candidate_mode": (
            "candidate generation reads site_selection.outlets.candidate_mode. Write "
            "the mode there."
        ),
    }

    principle: Annotated[SelectionPrinciple, Profile.USER] = Field(
        default="criteria_crossing",
        description="Selection principle: observation-led or direct criteria crossing.",
        json_schema_extra={
            "value_docs": {
                "observation_led": (
                    "Builds candidates from imported observation outlets, such as flow stations."
                ),
                "criteria_crossing": (
                    "Crosses the declared spatial and physical criteria directly, with "
                    "no observation-led outlets."
                ),
            }
        },
    )
    profile: Annotated[StrategyProfile | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional selection profile. Short-term supported profiles are "
            "'area_only' and 'gauged_downstream_station'."
        ),
    )
    primary_axes: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Physical or spatial axes that drive a criteria_crossing selection.",
    )
    observation_role: Annotated[ObservationRole, Profile.USER] = Field(
        default="report_only",
        description="How observations influence a criteria_crossing campaign.",
        json_schema_extra={"value_docs": OBSERVATION_ROLE_VALUE_DOCS},
    )
    geology_role: Annotated[ObservationRole, Profile.USER] = Field(
        default="report_only",
        description="How geology influences a criteria_crossing campaign.",
        json_schema_extra={"value_docs": OBSERVATION_ROLE_VALUE_DOCS},
    )
    primary_observation_type: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Observation family required by an observation_led strategy.",
    )
    observation_source: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Provider or normalized source used for primary observations.",
    )

    @model_validator(mode="after")
    def _validate_strategy(self) -> StrategyConfig:
        if self.principle == "observation_led":
            if not self.primary_observation_type:
                raise ValueError(
                    "observation_led requires primary_observation_type "
                    "(for example 'flow_station')."
                )
            if self.profile != "gauged_downstream_station":
                raise ValueError("observation_led requires profile='gauged_downstream_station'.")

        if self.profile == "gauged_downstream_station":
            if self.principle != "observation_led":
                raise ValueError(
                    "profile='gauged_downstream_station' requires principle='observation_led'."
                )
            if self.primary_observation_type != "flow_station":
                raise ValueError(
                    "profile='gauged_downstream_station' requires "
                    "primary_observation_type='flow_station'."
                )

        if self.profile == "area_only":
            if self.principle != "criteria_crossing":
                raise ValueError("profile='area_only' requires principle='criteria_crossing'.")
            axes = {axis.strip().lower() for axis in self.primary_axes}
            if axes != {"area"}:
                raise ValueError("profile='area_only' requires primary_axes = ['area'].")
            if self.observation_role not in {"report_only", "ignore"}:
                raise ValueError("area_only requires observation_role='report_only' or 'ignore'.")
            if self.geology_role not in {"report_only", "ignore"}:
                raise ValueError("area_only requires geology_role='report_only' or 'ignore'.")

        return self


class TerritoryConfig(HydroModelBase):
    """Spatial domain where candidate basins are searched."""

    mode: Annotated[
        Literal[
            "admin_regions",
            "admin_departments",
            "polygon_file",
            "bbox",
        ],
        Profile.USER,
    ] = Field(
        default="bbox",
        description=(
            "How the search territory is given: by administrative regions, by departments, "
            "by a polygon file or by a bounding box. Each mode reads its own key."
        ),
        json_schema_extra={
            "value_docs": {
                "admin_regions": (
                    "Bounds the territory to the bounding box of the named administrative regions."
                ),
                "admin_departments": (
                    "Bounds the territory to the bounding box of the named departments."
                ),
                "polygon_file": (
                    "Bounds the territory to the bounding box of a user-supplied polygon file."
                ),
                "bbox": "Bounds the territory to an explicit xmin, ymin, xmax, ymax box.",
            }
        },
    )
    country: Annotated[str | None, Profile.USER] = Field(
        default="fr",
        description=(
            "Country code of the territory, in any case. With 'fr' the administrative "
            "modes read the French regions and departments, and the default CRS is "
            "Lambert-93 (EPSG:2154). The administrative modes need 'fr'. Another "
            "code gives no default CRS."
        ),
    )
    regions: Annotated[list[str], Profile.USER, VisibleWhen("mode", "admin_regions")] = Field(
        default_factory=list,
        description=(
            "Names of the administrative regions that bound the territory, checked "
            "against the French regions."
        ),
        examples=[["Bretagne"]],
    )
    departments: Annotated[list[str], Profile.USER, VisibleWhen("mode", "admin_departments")] = (
        Field(
            default_factory=list,
            description="Codes of the administrative departments that bound the territory.",
            examples=[["35", "56"]],
        )
    )
    polygon_file: Annotated[Path | None, Profile.USER, VisibleWhen("mode", "polygon_file")] = Field(
        default=None,
        description="Vector file of a polygon whose bounding box is the territory.",
    )
    bbox: Annotated[tuple[float, float, float, float] | None, Profile.USER] = Field(
        default=None,
        description="Territory bounds as xmin, ymin, xmax, ymax.",
    )
    clip_to_territory: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Clip candidate basins or outlets to the requested territory.",
    )

    @model_validator(mode="after")
    def _validate_territory(self) -> TerritoryConfig:
        if self.mode in {"admin_regions", "admin_departments"} and (
            str(self.country or "").upper() != "FR"
        ):
            raise ValueError(
                f"mode={self.mode!r} needs country = 'fr', got country = {self.country!r}. "
                "HydroModPy knows the administrative geometry of France only. Write "
                "mode = 'polygon_file' or mode = 'bbox' for another country."
            )
        if self.mode == "admin_regions" and not self.regions:
            raise ValueError("mode='admin_regions' requires at least one region.")
        if self.mode == "admin_regions":
            object.__setattr__(self, "regions", validate_french_regions(self.regions))
        if self.mode == "admin_departments" and not self.departments:
            raise ValueError("mode='admin_departments' requires at least one department.")
        if self.mode == "polygon_file" and self.polygon_file is None:
            raise ValueError("mode='polygon_file' requires polygon_file.")
        if self.mode == "bbox" and self.bbox is None:
            raise ValueError("mode='bbox' requires bbox.")
        return self
