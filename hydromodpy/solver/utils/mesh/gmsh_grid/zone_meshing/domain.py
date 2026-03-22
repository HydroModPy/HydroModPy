"""Define the geometry payloads used by the zone-conformal meshing workflow.

This module is the bridge between input polygon datasets and the conformal
mesher. It loads, validates, and reshapes domain and zone geometries into a
small set of contracts that the meshing code can consume safely.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box
from shapely.ops import unary_union

from hydromodpy.data_managers.variables.geology.io import resolve_data_path

try:  # Shapely >= 2
    from shapely import make_valid as _shapely_make_valid
except ImportError:  # pragma: no cover - depends on environment
    from shapely.validation import make_valid as _shapely_make_valid  # type: ignore[no-redef]


@dataclass(frozen=True)
class ZoneMeshingDomainConfig:
    """Typed support-domain contract shared by conformal meshing workflows."""

    kind: str
    bbox: tuple[float, float, float, float] | None = None
    coordinates: tuple[tuple[float, float], ...] | None = None
    path: str | None = None
    id_field: str | None = None
    selected_id: str | None = None

    @classmethod
    def from_mapping(
        cls,
        config_data: Mapping[str, Any],
    ) -> "ZoneMeshingDomainConfig":
        """Validate one raw mapping and return one typed domain contract."""
        parsed = _validate_zone_meshing_domain_model(config_data)
        return cls.from_normalized_mapping(parsed.model_dump(mode="python"))

    @classmethod
    def from_normalized_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> "ZoneMeshingDomainConfig":
        """Build one typed domain contract from already normalized values."""
        bbox_raw = payload.get("bbox")
        coordinates_raw = payload.get("coordinates")
        return cls(
            kind=str(payload["kind"]),
            bbox=(
                None
                if bbox_raw is None
                else tuple(float(value) for value in bbox_raw)
            ),
            coordinates=(
                None
                if coordinates_raw is None
                else tuple((float(pair[0]), float(pair[1])) for pair in coordinates_raw)
            ),
            path=None if payload.get("path") is None else str(payload["path"]),
            id_field=(
                None if payload.get("id_field") is None else str(payload["id_field"])
            ),
            selected_id=(
                None
                if payload.get("selected_id") is None
                else str(payload["selected_id"])
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Serialize one typed domain contract to mapping form."""
        payload: dict[str, Any] = {"kind": self.kind}
        if self.bbox is not None:
            payload["bbox"] = [float(value) for value in self.bbox]
        if self.coordinates is not None:
            payload["coordinates"] = [
                [float(x), float(y)] for x, y in self.coordinates
            ]
        if self.path is not None:
            payload["path"] = self.path
        if self.id_field is not None:
            payload["id_field"] = self.id_field
        if self.selected_id is not None:
            payload["selected_id"] = self.selected_id
        return payload


@dataclass(frozen=True)
class ZoneMeshingDomainPayload:
    """Resolved geometry payload returned after loading one support domain."""

    geometry: object
    gdf: object
    summary: dict[str, Any]

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> "ZoneMeshingDomainPayload":
        """Build one typed geometry payload from plain mapping form."""
        return cls(
            geometry=payload["geometry"],
            gdf=payload["gdf"],
            summary=dict(payload.get("summary", {})),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Serialize one typed geometry payload to mapping form."""
        return {
            "geometry": self.geometry,
            "gdf": self.gdf,
            "summary": dict(self.summary),
        }


def parse_zone_meshing_domain_config(
    config_data: Mapping[str, Any],
) -> ZoneMeshingDomainConfig:
    """Return one typed support-domain contract from a raw mapping."""

    return ZoneMeshingDomainConfig.from_mapping(config_data)


class ZoneMeshingDomainBBoxSchema(BaseModel):
    """Axis-aligned bounding box domain contract."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(
        default="bbox",
        description=(
            "Use an explicit axis-aligned bounding box defined directly in the TOML. "
            "This is the most direct way to prescribe a synthetic rectangular support."
        ),
    )
    bbox: list[float] = Field(
        description=(
            "Bounding box coordinates ordered as [xmin, ymin, xmax, ymax] in the projected CRS used by the mesher."
        )
    )

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

    kind: str = Field(
        default="polygon",
        description=(
            "Use one polygon drawn directly in the TOML through its vertex coordinates. "
            "This is useful for compact synthetic cases or quick experiments."
        ),
    )
    coordinates: list[list[float]] = Field(
        description=(
            "Ordered polygon vertices as [[x1, y1], [x2, y2], ...] in the projected CRS used by the mesher."
        )
    )

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

    kind: str = Field(
        default="vector",
        description=(
            "Load the support domain from a polygon vector file such as SHP, GPKG, or GeoJSON."
        ),
    )
    path: str = Field(
        description=(
            "Path to the polygon vector dataset that defines the support domain or one family of candidate polygons."
        )
    )
    id_field: str | None = Field(
        default=None,
        description=(
            "Optional attribute column used to select one polygon among several features in the vector file."
        ),
    )
    selected_id: str | None = Field(
        default=None,
        description=(
            "Optional identifier value to extract one feature when the vector file contains multiple polygons."
        ),
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
            raise ValueError(
                "domain.id_field is required when domain.selected_id is provided"
            )
        return self


class ZoneMeshingDomainGeographicBoxBufferSchema(BaseModel):
    """Domain resolved from ``domain_geographic.box_buff_shp``."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(
        default="geographic_box_buffer",
        description=(
            "Reuse the buffered catchment box prepared by the geographic workflow. "
            "This is usually the most convenient support for catchment meshing because it preserves some context around the watershed."
        ),
    )

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

    kind: str = Field(
        default="geographic_watershed",
        description=(
            "Reuse the strict watershed polygon prepared by the geographic workflow. "
            "Choose this mode when the mesh should not extend beyond the catchment outline."
        ),
    )

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

    kind: str = Field(
        default="geographic_watershed_box",
        description=(
            "Reuse the unbuffered bounding box around the watershed polygon. "
            "This is a useful intermediate scope when you want more context than the strict watershed but less than the full buffered box."
        ),
    )

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value):
        if str(value).strip().lower() != "geographic_watershed_box":
            raise ValueError(
                "geographic watershed-box domain kind must be 'geographic_watershed_box'"
            )
        return "geographic_watershed_box"


def _make_valid_geometry(geometry):
    if geometry is None:
        return GeometryCollection()
    if geometry.is_empty:
        return geometry
    fixed = _shapely_make_valid(geometry)
    if fixed.is_empty:
        return fixed
    try:
        repaired = fixed.buffer(0)
    except Exception:  # pragma: no cover - defensive only
        repaired = fixed
    return repaired


def _iter_polygon_parts(geometry):
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, Polygon):
        yield geometry
        return
    if isinstance(geometry, MultiPolygon):
        for polygon in geometry.geoms:
            if not polygon.is_empty:
                yield polygon
        return
    if isinstance(geometry, GeometryCollection):
        for sub_geometry in geometry.geoms:
            yield from _iter_polygon_parts(sub_geometry)


def _validate_zone_meshing_domain_model(config_data: Mapping[str, Any]) -> BaseModel:
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


def _geometry_to_summary_payload(
    *, geometry, kind: str, extras: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    bounds = [round(float(v), 6) for v in geometry.bounds]
    payload = {
        "domain_kind": str(kind),
        "domain_area": round(float(geometry.area), 12),
        "domain_bounds": bounds,
        "domain_geometry_type": str(geometry.geom_type),
    }
    if extras:
        payload.update({str(key): value for key, value in extras.items()})
    return payload


def load_zone_meshing_domain_payload(
    config: ZoneMeshingDomainConfig,
    *,
    config_path: str | Path | None = None,
    domain_geographic: object | None = None,
    target_crs=None,
) -> ZoneMeshingDomainPayload:
    """Load one domain geometry and return one typed payload."""

    import geopandas as gpd

    kind = str(config.kind)

    def _load_geographic_domain_from_attr(
        *,
        attr_name: str,
        domain_id: str,
        label: str,
    ) -> ZoneMeshingDomainPayload:
        if domain_geographic is None:
            raise ValueError(
                f"domain.kind='{kind}' requires one domain_geographic context."
            )
        raw_path = getattr(domain_geographic, attr_name, None)
        if raw_path is None:
            raise ValueError(
                f"domain.kind='{kind}' requires domain_geographic.{attr_name}."
            )
        source_path = Path(str(raw_path)).expanduser().resolve()
        gdf = gpd.read_file(source_path)
        if gdf.empty:
            raise ValueError(
                f"{label} domain source has no geometry: {source_path}"
            )
        gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
        if gdf.empty:
            raise ValueError(
                f"{label} domain source has only empty geometries: {source_path}"
            )
        source_crs = gdf.crs
        if (
            target_crs is not None
            and source_crs is not None
            and source_crs != target_crs
        ):
            gdf = gdf.to_crs(target_crs)

        geometry = _make_valid_geometry(unary_union(list(gdf.geometry)))
        polygons = [
            polygon
            for polygon in _iter_polygon_parts(geometry)
            if float(polygon.area) > 0.0
        ]
        if not polygons:
            raise ValueError(
                f"{label} domain produced no usable polygon after cleaning: "
                f"{source_path}"
            )
        geometry = unary_union(polygons)
        domain_gdf = gpd.GeoDataFrame(
            {"domain_id": [domain_id]},
            geometry=[geometry],
            crs=gdf.crs,
        )
        return ZoneMeshingDomainPayload(
            geometry=geometry,
            gdf=domain_gdf,
            summary=_geometry_to_summary_payload(
                geometry=geometry,
                kind=kind,
                extras={
                    "domain_source_path": str(source_path),
                    "domain_source_feature_count": int(len(gdf)),
                    "domain_crs": None if gdf.crs is None else str(gdf.crs),
                },
            ),
        )

    if kind == "bbox":
        if config.bbox is None:  # pragma: no cover - validated upstream
            raise ValueError("bbox domain requires bbox coordinates")
        geometry = box(*config.bbox)
        domain_gdf = gpd.GeoDataFrame(
            {"domain_id": ["bbox_domain"]}, geometry=[geometry], crs=target_crs
        )
        return ZoneMeshingDomainPayload(
            geometry=geometry,
            gdf=domain_gdf,
            summary=_geometry_to_summary_payload(
                geometry=geometry,
                kind=kind,
                extras={"domain_bbox": [round(float(v), 6) for v in config.bbox]},
            ),
        )

    if kind == "geographic_box_buffer":
        return _load_geographic_domain_from_attr(
            attr_name="box_buff_shp",
            domain_id="geographic_box_buffer",
            label="Geographic box-buffer",
        )

    if kind == "geographic_watershed":
        return _load_geographic_domain_from_attr(
            attr_name="watershed_shp",
            domain_id="geographic_watershed",
            label="Geographic watershed",
        )

    if kind == "geographic_watershed_box":
        return _load_geographic_domain_from_attr(
            attr_name="watershed_box_shp",
            domain_id="geographic_watershed_box",
            label="Geographic watershed-box",
        )

    if kind == "polygon":
        if config.coordinates is None:  # pragma: no cover - validated upstream
            raise ValueError("polygon domain requires coordinates")
        geometry = _make_valid_geometry(Polygon(config.coordinates))
        polygons = [
            polygon
            for polygon in _iter_polygon_parts(geometry)
            if float(polygon.area) > 0.0
        ]
        if not polygons:
            raise ValueError("polygon domain produced no usable polygon")
        geometry = unary_union(polygons)
        domain_gdf = gpd.GeoDataFrame(
            {"domain_id": ["inline_polygon_domain"]},
            geometry=[geometry],
            crs=target_crs,
        )
        return ZoneMeshingDomainPayload(
            geometry=geometry,
            gdf=domain_gdf,
            summary=_geometry_to_summary_payload(
                geometry=geometry,
                kind=kind,
                extras={"domain_vertex_count": int(len(config.coordinates))},
            ),
        )

    if config.path is None:  # pragma: no cover - validated upstream
        raise ValueError("vector domain requires path")
    source_path = Path(resolve_data_path(config.path, config_path=config_path)).resolve()
    gdf = gpd.read_file(source_path)
    if gdf.empty:
        raise ValueError(f"Domain vector source has no geometry: {source_path}")
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
    if gdf.empty:
        raise ValueError(
            f"Domain vector source has only empty geometries: {source_path}"
        )

    n_source_features = int(len(gdf))
    id_field = config.id_field
    selected_id = config.selected_id
    if id_field is not None:
        if id_field not in gdf.columns:
            raise KeyError(f"Missing domain id field '{id_field}' in {source_path}")
        if selected_id is not None:
            gdf = gdf.loc[gdf[id_field].astype(str) == str(selected_id)].copy()
            if gdf.empty:
                raise ValueError(
                    f"Domain vector source contains no feature with {id_field}={selected_id!r}: {source_path}"
                )

    source_crs = gdf.crs
    if (
        target_crs is not None
        and source_crs is not None
        and source_crs != target_crs
    ):
        gdf = gdf.to_crs(target_crs)

    geometry = _make_valid_geometry(unary_union(list(gdf.geometry)))
    polygons = [
        polygon
        for polygon in _iter_polygon_parts(geometry)
        if float(polygon.area) > 0.0
    ]
    if not polygons:
        raise ValueError(
            f"Domain vector source produced no usable polygon after cleaning: {source_path}"
        )
    geometry = unary_union(polygons)
    domain_gdf = gpd.GeoDataFrame(
        {"domain_id": ["domain_source"]},
        geometry=[geometry],
        crs=gdf.crs,
    )
    return ZoneMeshingDomainPayload(
        geometry=geometry,
        gdf=domain_gdf,
        summary=_geometry_to_summary_payload(
            geometry=geometry,
            kind=kind,
            extras={
                "domain_source_path": str(source_path),
                "domain_id_field": None if id_field is None else str(id_field),
                "domain_selected_id": None if selected_id is None else str(selected_id),
                "domain_source_feature_count": int(n_source_features),
                "domain_selected_feature_count": int(len(gdf)),
                "domain_crs": None if gdf.crs is None else str(gdf.crs),
            },
        ),
    )


__all__ = [
    "parse_zone_meshing_domain_config",
    "ZoneMeshingDomainConfig",
    "ZoneMeshingDomainPayload",
    "load_zone_meshing_domain_payload",
]
