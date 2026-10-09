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
from hydromodpy.core.config_kit.types import NonEmptyPath, NonEmptyStr


class ZoneMeshingDomainBBox(HydroModelBase):
    """A rectangle given by bbox = [xmin, ymin, xmax, ymax]."""

    kind: Annotated[Literal["bbox"], Profile.USER] = Field(
        default="bbox",
        description=(
            "Where the outline of the meshed domain comes from. Unset, it follows from "
            "the key given: bbox, coordinates or path."
        ),
    )
    bbox: Annotated[list[float], Profile.USER] = Field(
        description=(
            "Rectangle of the domain as [xmin, ymin, xmax, ymax], in metres in the "
            "projected CRS of the project."
        ),
        examples=[[350000.0, 6780000.0, 362000.0, 6792000.0]],
        json_schema_extra={"unit": "m"},
    )

    @field_validator("bbox", mode="before")
    @classmethod
    def _normalize_bbox(cls, value):
        if not isinstance(value, (list, tuple)):
            return value
        coords = [float(v) for v in value]
        if len(coords) != 4:
            raise ValueError("bbox domain requires 4 values: xmin, ymin, xmax, ymax")
        xmin, ymin, xmax, ymax = coords
        if not (xmax > xmin and ymax > ymin):
            raise ValueError("bbox domain requires xmax > xmin and ymax > ymin")
        return [xmin, ymin, xmax, ymax]


class ZoneMeshingDomainPolygon(HydroModelBase):
    """A polygon given inline by its vertices."""

    kind: Annotated[Literal["polygon"], Profile.USER] = "polygon"
    coordinates: Annotated[list[list[float]], Profile.USER] = Field(
        description=(
            "Vertices [[x, y], ...] of the domain polygon, at least three, in metres in "
            "the projected CRS of the project."
        ),
        examples=[[[350000.0, 6780000.0], [362000.0, 6780000.0], [356000.0, 6792000.0]]],
        json_schema_extra={"unit": "m"},
    )

    @field_validator("coordinates")
    @classmethod
    def _validate_coordinates(cls, value):
        coords = [[float(v[0]), float(v[1])] for v in value]
        if len(coords) < 3:
            raise ValueError("polygon domain requires at least 3 coordinate pairs")
        return coords


class ZoneMeshingDomainVector(HydroModelBase):
    """A polygon read from a vector file."""

    kind: Annotated[Literal["vector"], Profile.USER] = "vector"
    path: Annotated[NonEmptyPath, Profile.USER] = Field(
        description="Vector file (gpkg, shp, GeoJSON) holding the polygon of the meshed domain.",
        examples=["domain.gpkg"],
    )
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
    """The buffered rectangle around the catchment that [geographic] builds."""

    kind: Annotated[Literal["geographic_box_buffer"], Profile.USER] = "geographic_box_buffer"


class ZoneMeshingDomainGeographicWatershed(HydroModelBase):
    """The catchment polygon that [geographic] delineates."""

    kind: Annotated[Literal["geographic_watershed"], Profile.USER] = "geographic_watershed"


class ZoneMeshingDomainGeographicWatershedBox(HydroModelBase):
    """The bounding rectangle of the catchment that [geographic] delineates."""

    kind: Annotated[Literal["geographic_watershed_box"], Profile.USER] = "geographic_watershed_box"


ZoneMeshingDomain: TypeAlias = Annotated[
    ZoneMeshingDomainBBox
    | ZoneMeshingDomainPolygon
    | ZoneMeshingDomainVector
    | ZoneMeshingDomainGeographicBoxBuffer
    | ZoneMeshingDomainGeographicWatershed
    | ZoneMeshingDomainGeographicWatershedBox,
    Field(discriminator="kind", description="Zone-meshing domain kind discriminator."),
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
