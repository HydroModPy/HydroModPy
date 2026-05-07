"""Validation schemas for zone-meshing support domains."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import NonEmptyStr


class ZoneMeshingDomainBBox(HydroModelBase):
    """Axis-aligned bounding box domain contract."""

    kind: Annotated[Literal["bbox"], Profile.USER] = "bbox"
    bbox: Annotated[list[float], Profile.USER]

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

    kind: Annotated[Literal["polygon"], Profile.USER] = "polygon"
    coordinates: Annotated[list[list[float]], Profile.USER]

    @field_validator("coordinates")
    @classmethod
    def _validate_coordinates(cls, value):
        coords = [[float(v[0]), float(v[1])] for v in value]
        if len(coords) < 3:
            raise ValueError("polygon domain requires at least 3 coordinate pairs")
        return coords


class ZoneMeshingDomainVector(HydroModelBase):
    """Vector file domain contract."""

    kind: Annotated[Literal["vector"], Profile.USER] = "vector"
    path: Annotated[NonEmptyStr, Profile.USER]
    id_field: Annotated[NonEmptyStr | None, Profile.USER] = Field(
        default=None,
        description="Optional vector attribute field name used to filter features.",
    )
    selected_id: Annotated[NonEmptyStr | None, Profile.USER] = Field(
        default=None,
        description="Optional value of id_field that selects a single feature in the vector source.",
    )

    @model_validator(mode="after")
    def _validate_selector(self):
        if (self.selected_id is not None) and (self.id_field is None):
            raise ValueError("domain.id_field is required when domain.selected_id is provided")
        return self


class ZoneMeshingDomainGeographicBoxBuffer(HydroModelBase):
    """Domain resolved from ``domain_geographic.box_buff_shp``."""

    kind: Annotated[Literal["geographic_box_buffer"], Profile.USER] = "geographic_box_buffer"


class ZoneMeshingDomainGeographicWatershed(HydroModelBase):
    """Domain resolved from ``domain_geographic.watershed_shp``."""

    kind: Annotated[Literal["geographic_watershed"], Profile.USER] = "geographic_watershed"


class ZoneMeshingDomainGeographicWatershedBox(HydroModelBase):
    """Domain resolved from ``domain_geographic.watershed_box_shp``."""

    kind: Annotated[Literal["geographic_watershed_box"], Profile.USER] = "geographic_watershed_box"


ZoneMeshingDomain: TypeAlias = Annotated[
    ZoneMeshingDomainBBox
    | ZoneMeshingDomainPolygon
    | ZoneMeshingDomainVector
    | ZoneMeshingDomainGeographicBoxBuffer
    | ZoneMeshingDomainGeographicWatershed
    | ZoneMeshingDomainGeographicWatershedBox,
    Field(discriminator="kind"),
]
"""Discriminated union of zone-meshing support domain schemas."""


_DOMAIN_ADAPTER: TypeAdapter[ZoneMeshingDomain] = TypeAdapter(ZoneMeshingDomain)


_KIND_BY_KEY: dict[str, str] = {
    "bbox": "bbox",
    "coordinates": "polygon",
    "path": "vector",
}


def validate_zone_meshing_domain_model(config_data: Mapping[str, Any]) -> BaseModel:
    """Validate one domain mapping and return the concrete schema instance."""
    if not isinstance(config_data, Mapping):
        raise ValueError("domain configuration must be a mapping")
    raw = dict(config_data)

    kind = str(raw.get("kind", "")).strip().lower()
    if kind == "":
        for key, inferred_kind in _KIND_BY_KEY.items():
            if key in raw:
                kind = inferred_kind
                break
        else:
            raise ValueError(
                "domain configuration requires one explicit geometry source: "
                "'bbox', 'coordinates', or 'path'"
            )
    raw["kind"] = kind

    try:
        return _DOMAIN_ADAPTER.validate_python(raw)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
