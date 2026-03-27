"""Validation schemas for zone-meshing support domains."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


class ZoneMeshingDomainBBoxSchema(BaseModel):
    """Axis-aligned bounding box domain contract."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default="bbox")
    bbox: list[float]

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
        self.bbox = [xmin, ymin, xmax, ymax]
        return self


class ZoneMeshingDomainPolygonSchema(BaseModel):
    """Inline polygon coordinates domain contract."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default="polygon")
    coordinates: list[list[float]]

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


class ZoneMeshingDomainVectorSchema(BaseModel):
    """Vector file domain contract."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default="vector")
    path: str
    id_field: str | None = Field(default=None)
    selected_id: str | None = Field(default=None)

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
            raise ValueError(
                "domain.id_field is required when domain.selected_id is provided"
            )
        return self


class ZoneMeshingDomainGeographicBoxBufferSchema(BaseModel):
    """Domain resolved from ``domain_geographic.box_buff_shp``."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default="geographic_box_buffer")

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value):
        if str(value).strip().lower() != "geographic_box_buffer":
            raise ValueError(
                "geographic box-buffer domain kind must be 'geographic_box_buffer'"
            )
        return "geographic_box_buffer"


class ZoneMeshingDomainGeographicWatershedSchema(BaseModel):
    """Domain resolved from ``domain_geographic.watershed_shp``."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default="geographic_watershed")

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value):
        if str(value).strip().lower() != "geographic_watershed":
            raise ValueError(
                "geographic watershed domain kind must be 'geographic_watershed'"
            )
        return "geographic_watershed"


class ZoneMeshingDomainGeographicWatershedBoxSchema(BaseModel):
    """Domain resolved from ``domain_geographic.watershed_box_shp``."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default="geographic_watershed_box")

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
        "bbox": ZoneMeshingDomainBBoxSchema,
        "geographic_box_buffer": ZoneMeshingDomainGeographicBoxBufferSchema,
        "geographic_watershed": ZoneMeshingDomainGeographicWatershedSchema,
        "geographic_watershed_box": ZoneMeshingDomainGeographicWatershedBoxSchema,
        "polygon": ZoneMeshingDomainPolygonSchema,
        "vector": ZoneMeshingDomainVectorSchema,
    }
    if kind not in schema_by_kind:
        allowed = ", ".join(sorted(schema_by_kind))
        raise ValueError(f"Unsupported domain.kind '{kind}'. Allowed: {allowed}")
    try:
        return schema_by_kind[kind].model_validate(raw)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
