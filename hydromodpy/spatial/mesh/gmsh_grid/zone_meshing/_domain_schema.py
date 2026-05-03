"""Validation schemas for zone-meshing support domains."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile


class ZoneMeshingDomainBBox(HydroModelBase):
    """Axis-aligned bounding box domain contract."""

    model_config = ConfigDict(extra="forbid")

    kind: Annotated[str, Profile.USER] = Field(
        default="bbox",
        description="Domain kind discriminator, must be 'bbox' for this schema.",
    )
    bbox: Annotated[list[float], Profile.USER]

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value):
        if str(value).strip().lower() != "bbox":
            raise ValueError("bbox domain kind must be 'bbox'")
        return "bbox"

    @model_validator(mode="after")
    def _validate_bbox(self):
        coords = [float(v) for v in self.bbox]
        if len(coords) != 4:
            raise ValueError("bbox domain requires 4 values: xmin, ymin, xmax, ymax")
        xmin, ymin, xmax, ymax = coords
        if not (xmax > xmin and ymax > ymin):
            raise ValueError("bbox domain requires xmax > xmin and ymax > ymin")
        object.__setattr__(self, "bbox", [xmin, ymin, xmax, ymax])
        return self


class ZoneMeshingDomainPolygon(HydroModelBase):
    """Inline polygon coordinates domain contract."""

    model_config = ConfigDict(extra="forbid")

    kind: Annotated[str, Profile.USER] = Field(
        default="polygon",
        description="Domain kind discriminator, must be 'polygon' for this schema.",
    )
    coordinates: Annotated[list[list[float]], Profile.USER]

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value):
        if str(value).strip().lower() != "polygon":
            raise ValueError("polygon domain kind must be 'polygon'")
        return "polygon"

    @field_validator("coordinates")
    @classmethod
    def _validate_coordinates(cls, value):
        coords = [[float(v[0]), float(v[1])] for v in value]
        if len(coords) < 3:
            raise ValueError("polygon domain requires at least 3 coordinate pairs")
        return coords


class ZoneMeshingDomainVector(HydroModelBase):
    """Vector file domain contract."""

    model_config = ConfigDict(extra="forbid")

    kind: Annotated[str, Profile.USER] = Field(
        default="vector",
        description="Domain kind discriminator, must be 'vector' for this schema.",
    )
    path: Annotated[str, Profile.USER]
    id_field: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional vector attribute field name used to filter features.",
    )
    selected_id: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional value of id_field that selects a single feature in the vector source.",
    )

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value):
        if str(value).strip().lower() != "vector":
            raise ValueError("vector domain kind must be 'vector'")
        return "vector"

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value):
        text = str(value).strip()
        if not text:
            raise ValueError("domain.path cannot be empty")
        return text

    @field_validator("id_field", "selected_id")
    @classmethod
    def _validate_optional_text(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("domain selector values cannot be empty when provided")
        return text

    @model_validator(mode="after")
    def _validate_selector(self):
        if (self.selected_id is not None) and (self.id_field is None):
            raise ValueError("domain.id_field is required when domain.selected_id is provided")
        return self


class ZoneMeshingDomainGeographicBoxBuffer(HydroModelBase):
    """Domain resolved from ``domain_geographic.box_buff_shp``."""

    model_config = ConfigDict(extra="forbid")

    kind: Annotated[str, Profile.USER] = Field(
        default="geographic_box_buffer",
        description="Domain kind discriminator, must be 'geographic_box_buffer' for this schema.",
    )

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value):
        if str(value).strip().lower() != "geographic_box_buffer":
            raise ValueError("geographic box-buffer domain kind must be 'geographic_box_buffer'")
        return "geographic_box_buffer"


class ZoneMeshingDomainGeographicWatershed(HydroModelBase):
    """Domain resolved from ``domain_geographic.watershed_shp``."""

    model_config = ConfigDict(extra="forbid")

    kind: Annotated[str, Profile.USER] = Field(
        default="geographic_watershed",
        description="Domain kind discriminator, must be 'geographic_watershed' for this schema.",
    )

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value):
        if str(value).strip().lower() != "geographic_watershed":
            raise ValueError("geographic watershed domain kind must be 'geographic_watershed'")
        return "geographic_watershed"


class ZoneMeshingDomainGeographicWatershedBox(HydroModelBase):
    """Domain resolved from ``domain_geographic.watershed_box_shp``."""

    model_config = ConfigDict(extra="forbid")

    kind: Annotated[str, Profile.USER] = Field(
        default="geographic_watershed_box",
        description="Domain kind discriminator, must be 'geographic_watershed_box' for this schema.",
    )

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value):
        if str(value).strip().lower() != "geographic_watershed_box":
            raise ValueError(
                "geographic watershed-box domain kind must be 'geographic_watershed_box'"
            )
        return "geographic_watershed_box"


def validate_zone_meshing_domain_model(config_data: Mapping[str, Any]) -> BaseModel:
    """Validate one domain mapping and return the concrete schema instance."""
    if not isinstance(config_data, Mapping):
        raise ValueError("domain configuration must be a mapping")
    raw = dict(config_data)

    kind = str(raw.get("kind", "")).strip().lower()
    if kind == "":
        if "bbox" in raw:
            kind = "bbox"
        elif "coordinates" in raw:
            kind = "polygon"
        elif "path" in raw:
            kind = "vector"
        else:
            raise ValueError(
                "domain configuration requires one explicit geometry source: "
                "'bbox', 'coordinates', or 'path'"
            )
        raw["kind"] = kind

    schema_by_kind: dict[str, type[BaseModel]] = {
        "bbox": ZoneMeshingDomainBBox,
        "geographic_box_buffer": ZoneMeshingDomainGeographicBoxBuffer,
        "geographic_watershed": ZoneMeshingDomainGeographicWatershed,
        "geographic_watershed_box": ZoneMeshingDomainGeographicWatershedBox,
        "polygon": ZoneMeshingDomainPolygon,
        "vector": ZoneMeshingDomainVector,
    }
    if kind not in schema_by_kind:
        allowed = ", ".join(sorted(schema_by_kind))
        raise ValueError(f"Unsupported domain.kind '{kind}'. Allowed: {allowed}")
    try:
        return schema_by_kind[kind].model_validate(raw)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
