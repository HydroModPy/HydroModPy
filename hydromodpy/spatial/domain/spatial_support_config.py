from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import CellSamplingDensity, NonEmptyStr
from hydromodpy.core.units import parse_length_to_m


class DomainSupportBaseConfig(HydroModelBase):
    """Base schema for one named spatial-support declaration.

    Concrete variants are unified through :data:`DomainSupportConfig`,
    a discriminated union over the ``kind`` literal.
    """


class GeneratedBandsSupportConfig(DomainSupportBaseConfig):
    """Analytical bands split along one cartesian axis."""

    kind: Annotated[Literal["generated_bands"], Profile.USER]
    axis: Annotated[Literal["x", "y"], Profile.USER] = "x"
    coordinate_mode: Annotated[Literal["relative", "absolute"], Profile.DEV] = "relative"
    breaks: Annotated[list[float | str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Ordered break coordinates delimiting consecutive bands. "
            "With coordinate_mode='relative', values are fractions in ]0,1[. "
            "With coordinate_mode='absolute', values are converted to metres."
        ),
    )
    labels: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Ordered band labels. Length must be len(breaks)+1.",
    )
    default_cell_samples_per_axis: Annotated[CellSamplingDensity, Profile.DEV] = Field(
        default=8,
        description="Sub-sampling resolution per cell axis used when rasterizing band masks.",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_breaks_and_labels(cls, value):
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        coordinate_mode = str(payload.get("coordinate_mode", "relative")).strip().lower()
        raw_breaks = payload.get("breaks") or []
        if not isinstance(raw_breaks, list):
            return payload
        normalized: list[float] = []
        for index, raw_break in enumerate(raw_breaks):
            if coordinate_mode == "relative":
                value_m = float(raw_break)
                if not 0.0 < value_m < 1.0:
                    raise ValueError(
                        "Relative generated_bands breaks must lie strictly between 0 and 1."
                    )
            else:
                value_m = float(
                    parse_length_to_m(
                        raw_break,
                        default_unit="m",
                        label=f"domain.supports.breaks[{index}]",
                    )
                )
                if value_m <= 0.0:
                    raise ValueError("Absolute generated_bands breaks must be > 0.")
            normalized.append(value_m)
        payload["breaks"] = normalized
        raw_labels = payload.get("labels") or []
        if isinstance(raw_labels, list):
            payload["labels"] = [str(raw).strip() for raw in raw_labels]
        return payload

    @model_validator(mode="after")
    def _validate_consistency(self) -> GeneratedBandsSupportConfig:
        if self.breaks != sorted(self.breaks):
            raise ValueError("domain.supports.<id>.breaks must be strictly increasing.")
        if len(set(self.breaks)) != len(self.breaks):
            raise ValueError("domain.supports.<id>.breaks cannot contain duplicates.")
        if any(label == "" for label in self.labels):
            raise ValueError("domain.supports.<id>.labels cannot contain empty values.")
        if len(self.labels) != len(self.breaks) + 1:
            raise ValueError("domain.supports.<id>.labels length must be len(breaks) + 1.")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("domain.supports.<id>.labels cannot contain duplicates.")
        return self


class GeneratedRingsSupportConfig(DomainSupportBaseConfig):
    """Analytical concentric rings centered on one cartesian point."""

    kind: Annotated[Literal["generated_rings"], Profile.USER]
    coordinate_mode: Annotated[Literal["relative", "absolute"], Profile.DEV] = "relative"
    radii: Annotated[list[float | str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Ordered ring radii delimiting consecutive concentric zones. "
            "With coordinate_mode='relative', values are fractions in ]0,1[ "
            "of the largest inscribed circle around the chosen center. "
            "With coordinate_mode='absolute', values are converted to metres."
        ),
    )
    labels: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Ordered ring labels. Length must be len(radii)+1.",
    )
    center_x: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional x coordinate of the ring center in projected metres. "
            "Defaults to the domain midpoint."
        ),
    )
    center_y: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional y coordinate of the ring center in projected metres. "
            "Defaults to the domain midpoint."
        ),
    )
    default_cell_samples_per_axis: Annotated[CellSamplingDensity, Profile.DEV] = Field(
        default=8,
        description="Sub-sampling resolution per cell axis used when rasterizing ring masks.",
    )

    @field_validator("center_x", "center_y", mode="before")
    @classmethod
    def _normalize_optional_centers(cls, value, info):
        if value is None:
            return None
        return float(
            parse_length_to_m(
                value,
                default_unit="m",
                label=f"domain.supports.{info.field_name}",
            )
        )

    @model_validator(mode="before")
    @classmethod
    def _normalize_radii_and_labels(cls, value):
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        coordinate_mode = str(payload.get("coordinate_mode", "relative")).strip().lower()
        raw_radii = payload.get("radii") or []
        if not isinstance(raw_radii, list):
            return payload
        normalized: list[float] = []
        for index, raw_radius in enumerate(raw_radii):
            if coordinate_mode == "relative":
                value_m = float(raw_radius)
                if not 0.0 < value_m < 1.0:
                    raise ValueError(
                        "Relative generated_rings radii must lie strictly between 0 and 1."
                    )
            else:
                value_m = float(
                    parse_length_to_m(
                        raw_radius,
                        default_unit="m",
                        label=f"domain.supports.radii[{index}]",
                    )
                )
                if value_m <= 0.0:
                    raise ValueError("Absolute generated_rings radii must be > 0.")
            normalized.append(value_m)
        payload["radii"] = normalized
        raw_labels = payload.get("labels") or []
        if isinstance(raw_labels, list):
            payload["labels"] = [str(raw).strip() for raw in raw_labels]
        return payload

    @model_validator(mode="after")
    def _validate_rings_consistency(self) -> GeneratedRingsSupportConfig:
        if self.radii != sorted(self.radii):
            raise ValueError("domain.supports.<id>.radii must be strictly increasing.")
        if len(set(self.radii)) != len(self.radii):
            raise ValueError("domain.supports.<id>.radii cannot contain duplicates.")
        if any(label == "" for label in self.labels):
            raise ValueError("domain.supports.<id>.labels cannot contain empty values.")
        if len(self.labels) != len(self.radii) + 1:
            raise ValueError("domain.supports.<id>.labels length must be len(radii) + 1.")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("domain.supports.<id>.labels cannot contain duplicates.")
        return self


class CatchmentZonesSupportConfig(DomainSupportBaseConfig):
    """Support built from catchment/domain zonation already prepared in setup."""

    kind: Annotated[Literal["catchment_zones"], Profile.USER]
    source_zone_id: Annotated[NonEmptyStr, Profile.USER] = Field(
        default="catchment",
        description="Domain zone id providing the source catchment zonation.",
    )
    default_cell_samples_per_axis: Annotated[CellSamplingDensity, Profile.DEV] = Field(
        default=8,
        description="Sub-sampling resolution per cell axis used when rasterizing zone masks.",
    )


class GeologySupportConfig(DomainSupportBaseConfig):
    """Support backed by the geology data manager."""

    kind: Annotated[Literal["geology"], Profile.USER]


DomainSupportConfig = Annotated[
    GeneratedBandsSupportConfig
    | GeneratedRingsSupportConfig
    | CatchmentZonesSupportConfig
    | GeologySupportConfig,
    Field(
        discriminator="kind",
        description="Discriminated union of spatial-support kinds selected by kind tag.",
    ),
]
