"""Define the geometry payloads used by the zone-conformal meshing workflow.

This module is the bridge between input polygon datasets and the conformal
mesher. It loads, validates, and reshapes domain and zone geometries into a
small set of contracts that the meshing code can consume safely.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box
from shapely.ops import unary_union

from hydromodpy.data_managers.geology.geology_io import resolve_data_path

try:  # Shapely >= 2
    from shapely import make_valid as _shapely_make_valid
except ImportError:  # pragma: no cover - depends on environment
    from shapely.validation import make_valid as _shapely_make_valid  # type: ignore[no-redef]


CLIP_BBOX_REMOVAL_MESSAGE = "domain.clip_bbox is no longer supported; use domain.kind='bbox' with domain.bbox instead."


class ZoneMeshingDomainBBoxSchema(BaseModel):
    """Axis-aligned bounding box domain contract."""

    model_config = ConfigDict(extra="forbid")

    kind: str = "bbox"
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

    kind: str = "polygon"
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

    kind: str = "vector"
    path: str
    id_field: str | None = None
    selected_id: str | None = None

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

    kind: str = "geographic_box_buffer"

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

    kind: str = "geographic_watershed"

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

    kind: str = "geographic_watershed_box"

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


def validate_zone_meshing_domain_config_data(
    config_data: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one domain meshing config block.

    The legacy key `clip_bbox` is rejected and must be migrated to
    `kind='bbox'` + `bbox=[xmin, ymin, xmax, ymax]`.
    """

    if not isinstance(config_data, Mapping):
        raise ValueError("domain configuration must be a mapping")
    raw = dict(config_data)
    if "clip_bbox" in raw:
        raise ValueError(CLIP_BBOX_REMOVAL_MESSAGE)

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
        parsed = schema_by_kind[kind].model_validate(raw)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python")


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


def load_zone_meshing_domain_geometry(
    config: Mapping[str, Any],
    *,
    config_path: str | Path | None = None,
    domain_geographic: object | None = None,
    target_crs=None,
    validate: bool = True,
) -> dict[str, Any]:
    """Load one domain geometry from bbox, inline polygon, or vector source."""

    import geopandas as gpd

    cfg = validate_zone_meshing_domain_config_data(config) if validate else dict(config)
    kind = str(cfg["kind"])

    def _load_geographic_domain_from_attr(
        *,
        attr_name: str,
        domain_id: str,
        label: str,
    ) -> dict[str, Any]:
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
        if target_crs is not None and source_crs is not None and source_crs != target_crs:
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
        return {
            "geometry": geometry,
            "gdf": domain_gdf,
            "summary": _geometry_to_summary_payload(
                geometry=geometry,
                kind=kind,
                extras={
                    "domain_source_path": str(source_path),
                    "domain_source_feature_count": int(len(gdf)),
                    "domain_crs": None if gdf.crs is None else str(gdf.crs),
                },
            ),
        }

    if kind == "bbox":
        geometry = box(*cfg["bbox"])
        domain_gdf = gpd.GeoDataFrame(
            {"domain_id": ["bbox_domain"]}, geometry=[geometry], crs=target_crs
        )
        return {
            "geometry": geometry,
            "gdf": domain_gdf,
            "summary": _geometry_to_summary_payload(
                geometry=geometry,
                kind=kind,
                extras={"domain_bbox": [round(float(v), 6) for v in cfg["bbox"]]},
            ),
        }

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
        geometry = _make_valid_geometry(Polygon(cfg["coordinates"]))
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
        return {
            "geometry": geometry,
            "gdf": domain_gdf,
            "summary": _geometry_to_summary_payload(
                geometry=geometry,
                kind=kind,
                extras={"domain_vertex_count": int(len(cfg["coordinates"]))},
            ),
        }

    source_path = Path(
        resolve_data_path(cfg["path"], config_path=config_path)
    ).resolve()
    gdf = gpd.read_file(source_path)
    if gdf.empty:
        raise ValueError(f"Domain vector source has no geometry: {source_path}")
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
    if gdf.empty:
        raise ValueError(
            f"Domain vector source has only empty geometries: {source_path}"
        )

    n_source_features = int(len(gdf))
    id_field = cfg.get("id_field")
    selected_id = cfg.get("selected_id")
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
    if target_crs is not None and source_crs is not None and source_crs != target_crs:
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
        {"domain_id": ["domain_source"]}, geometry=[geometry], crs=gdf.crs
    )
    return {
        "geometry": geometry,
        "gdf": domain_gdf,
        "summary": _geometry_to_summary_payload(
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
    }
