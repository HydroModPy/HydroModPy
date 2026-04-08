from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.core.units import parse_length_to_m


class DomainSupportBaseConfig(BaseModel):
    """Base schema for one named spatial-support declaration."""

    model_config = ConfigDict(extra="forbid")

    provider: Annotated[str, ParamLevel("user")]


class GeneratedBandsSupportConfig(DomainSupportBaseConfig):
    """Analytical bands split along one cartesian axis."""

    provider: Annotated[Literal["generated_bands"], ParamLevel("user")]
    axis: Annotated[Literal["x", "y"], ParamLevel("user")] = "x"
    coordinate_mode: Annotated[Literal["relative", "absolute"], ParamLevel("dev")] = "relative"
    breaks: Annotated[list[float | str], ParamLevel("user")] = Field(
        default_factory=list,
        description=(
            "Ordered break coordinates delimiting consecutive bands. "
            "With coordinate_mode='relative', values are fractions in ]0,1[. "
            "With coordinate_mode='absolute', values are converted to metres."
        ),
    )
    labels: Annotated[list[str], ParamLevel("user")] = Field(
        default_factory=list,
        description="Ordered band labels. Length must be len(breaks)+1.",
    )
    default_cell_samples_per_axis: Annotated[int, ParamLevel("dev")] = Field(default=8, ge=2)

    @field_validator("breaks", mode="before")
    @classmethod
    def _validate_breaks_input(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("domain.supports.<id>.breaks must be a list")
        return value

    @field_validator("labels", mode="before")
    @classmethod
    def _validate_labels_input(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("domain.supports.<id>.labels must be a list")
        return value

    @model_validator(mode="after")
    def _normalize_and_validate(self) -> "GeneratedBandsSupportConfig":
        normalized_breaks: list[float] = []
        for index, raw_break in enumerate(self.breaks):
            if self.coordinate_mode == "relative":
                value = float(raw_break)
                if not 0.0 < value < 1.0:
                    raise ValueError(
                        "Relative generated_bands breaks must lie strictly between 0 and 1."
                    )
            else:
                value = float(
                    parse_length_to_m(
                        raw_break,
                        default_unit="m",
                        label=f"domain.supports.breaks[{index}]",
                    )
                )
                if value <= 0.0:
                    raise ValueError("Absolute generated_bands breaks must be > 0.")
            normalized_breaks.append(value)

        if normalized_breaks != sorted(normalized_breaks):
            raise ValueError("domain.supports.<id>.breaks must be strictly increasing.")
        if len(set(normalized_breaks)) != len(normalized_breaks):
            raise ValueError("domain.supports.<id>.breaks cannot contain duplicates.")

        normalized_labels = [str(raw).strip() for raw in self.labels]
        if any(label == "" for label in normalized_labels):
            raise ValueError("domain.supports.<id>.labels cannot contain empty values.")
        if len(normalized_labels) != len(normalized_breaks) + 1:
            raise ValueError(
                "domain.supports.<id>.labels length must be len(breaks) + 1."
            )
        if len(set(normalized_labels)) != len(normalized_labels):
            raise ValueError("domain.supports.<id>.labels cannot contain duplicates.")

        self.breaks = normalized_breaks
        self.labels = normalized_labels
        return self


class GeneratedRingsSupportConfig(DomainSupportBaseConfig):
    """Analytical concentric rings centered on one cartesian point."""

    provider: Annotated[Literal["generated_rings"], ParamLevel("user")]
    coordinate_mode: Annotated[Literal["relative", "absolute"], ParamLevel("dev")] = "relative"
    radii: Annotated[list[float | str], ParamLevel("user")] = Field(
        default_factory=list,
        description=(
            "Ordered ring radii delimiting consecutive concentric zones. "
            "With coordinate_mode='relative', values are fractions in ]0,1[ "
            "of the largest inscribed circle around the chosen center. "
            "With coordinate_mode='absolute', values are converted to metres."
        ),
    )
    labels: Annotated[list[str], ParamLevel("user")] = Field(
        default_factory=list,
        description="Ordered ring labels. Length must be len(radii)+1.",
    )
    center_x: Annotated[float | None, ParamLevel("dev")] = Field(
        default=None,
        description=(
            "Optional x coordinate of the ring center in projected metres. "
            "Defaults to the domain midpoint."
        ),
    )
    center_y: Annotated[float | None, ParamLevel("dev")] = Field(
        default=None,
        description=(
            "Optional y coordinate of the ring center in projected metres. "
            "Defaults to the domain midpoint."
        ),
    )
    default_cell_samples_per_axis: Annotated[int, ParamLevel("dev")] = Field(default=8, ge=2)

    @field_validator("radii", mode="before")
    @classmethod
    def _validate_radii_input(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("domain.supports.<id>.radii must be a list")
        return value

    @field_validator("labels", mode="before")
    @classmethod
    def _validate_ring_labels_input(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("domain.supports.<id>.labels must be a list")
        return value

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

    @model_validator(mode="after")
    def _normalize_and_validate_rings(self) -> "GeneratedRingsSupportConfig":
        normalized_radii: list[float] = []
        for index, raw_radius in enumerate(self.radii):
            if self.coordinate_mode == "relative":
                value = float(raw_radius)
                if not 0.0 < value < 1.0:
                    raise ValueError(
                        "Relative generated_rings radii must lie strictly between 0 and 1."
                    )
            else:
                value = float(
                    parse_length_to_m(
                        raw_radius,
                        default_unit="m",
                        label=f"domain.supports.radii[{index}]",
                    )
                )
                if value <= 0.0:
                    raise ValueError("Absolute generated_rings radii must be > 0.")
            normalized_radii.append(value)

        if normalized_radii != sorted(normalized_radii):
            raise ValueError("domain.supports.<id>.radii must be strictly increasing.")
        if len(set(normalized_radii)) != len(normalized_radii):
            raise ValueError("domain.supports.<id>.radii cannot contain duplicates.")

        normalized_labels = [str(raw).strip() for raw in self.labels]
        if any(label == "" for label in normalized_labels):
            raise ValueError("domain.supports.<id>.labels cannot contain empty values.")
        if len(normalized_labels) != len(normalized_radii) + 1:
            raise ValueError(
                "domain.supports.<id>.labels length must be len(radii) + 1."
            )
        if len(set(normalized_labels)) != len(normalized_labels):
            raise ValueError("domain.supports.<id>.labels cannot contain duplicates.")

        self.radii = normalized_radii
        self.labels = normalized_labels
        return self


class CatchmentZonesSupportConfig(DomainSupportBaseConfig):
    """Support built from catchment/domain zonation already prepared in setup."""

    provider: Annotated[Literal["catchment_zones"], ParamLevel("user")]
    source_zone_id: Annotated[str, ParamLevel("user")] = Field(
        default="catchment",
        description="Domain zone id providing the source catchment zonation.",
    )
    default_cell_samples_per_axis: Annotated[int, ParamLevel("dev")] = Field(default=8, ge=2)

    @field_validator("source_zone_id", mode="before")
    @classmethod
    def _normalize_source_zone_id(cls, value):
        text = str(value).strip()
        if text == "":
            raise ValueError("source_zone_id cannot be empty")
        return text


class GeologySupportConfig(DomainSupportBaseConfig):
    """Support backed by the geology data manager."""

    provider: Annotated[Literal["geology"], ParamLevel("user")]


DomainSupportConfig = Annotated[
    GeneratedBandsSupportConfig
    | GeneratedRingsSupportConfig
    | CatchmentZonesSupportConfig
    | GeologySupportConfig,
    Field(discriminator="provider"),
]
