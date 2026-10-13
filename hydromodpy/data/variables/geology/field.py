"""The geology field of a run, built from the file the geology manager returned.

The manager hands back one ``FieldRecord`` pointing at a GeoPackage or a
raster; the solver needs a ``GeologyField``: each cell of the model support
mapped to a geological zone. The encoding reads the code column of the file
(``CODE_LEG`` for the BRGM maps, the ``code_field`` of a custom source) and
samples it on the raster support of the domain when there is one. A vector
source also keeps its zone polygons, reprojected to the model CRS and cut to
the support: the solvers read exact zone fractions from them.
"""

from __future__ import annotations

from typing import Any

BRGM_SOURCES = frozenset({"brgm_1m", "brgm_50k"})
BRGM_CODE_FIELD = "CODE_LEG"


def build_geology_field(field_record: Any, *, geology_cfg: Any, raster_support: Any) -> Any:
    """Encode the record's file into a ``GeologyField`` on the raster support, if any."""
    from hydromodpy.data.variables.geology.config import validate_geology_config_data
    from hydromodpy.data.variables.geology.io import (
        infer_source_kind,
        load_geology_encoded_grid,
        load_geology_encoded_grid_on_raster_support,
    )
    from hydromodpy.spatial.field.geology.geology_field import GeologyField

    data_path = str(field_record.data)
    source_kind = infer_source_kind(data_path)
    cfg_dict: dict[str, Any] = {
        "id": str(geology_cfg.id),
        "source": {
            "path": data_path,
            "kind": source_kind,
            "code_field": _code_field(field_record, geology_cfg),
            "all_touched": False,
        },
        "cell_samples_per_axis": int(geology_cfg.cell_samples_per_axis),
    }
    if source_kind == "vector":
        cfg_dict["source"]["reference_raster_path"] = data_path
    cfg = validate_geology_config_data(cfg_dict)
    if raster_support is not None and source_kind == "vector":
        loaded = load_geology_encoded_grid_on_raster_support(cfg, raster_support=raster_support)
    else:
        loaded = load_geology_encoded_grid(cfg)

    encoded_to_zone = loaded["encoded_to_zone"]
    zone_polygons = None
    if source_kind == "vector":
        zone_polygons = _zone_polygons(
            data_path,
            code_field=cfg_dict["source"]["code_field"],
            zone_keys=tuple(encoded_to_zone[code] for code in sorted(encoded_to_zone)),
            crs=loaded["crs"],
            raster_support=raster_support,
        )
    field = GeologyField(
        identifier=str(geology_cfg.id),
        encoded_codes=loaded["encoded_codes"],
        encoded_to_zone=encoded_to_zone,
        transform=loaded["transform"],
        crs=loaded["crs"],
        source_kind=str(loaded["source_kind"]),
        default_cell_samples_per_axis=int(geology_cfg.cell_samples_per_axis),
        zone_polygons=zone_polygons,
    )
    # The overview report re-opens the original vector for its map; it looks
    # for `source_path` on the field.
    field.source_path = data_path
    return field


def _zone_polygons(
    data_path: str,
    *,
    code_field: str,
    zone_keys: tuple[str, ...],
    crs: Any,
    raster_support: Any,
) -> Any:
    """The polygons of each zone, in the CRS of the encoded grid, cut to the support."""
    import geopandas as gpd

    from hydromodpy.data.variables.geology.processing import normalize_zone_key
    from hydromodpy.spatial.field.zone_fractions import ZonePolygons

    gdf = gpd.read_file(data_path)
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
    if gdf.crs is not None and crs is not None and gdf.crs != crs:
        gdf = gdf.to_crs(crs)
    keys = [normalize_zone_key(raw) for raw in gdf[code_field]]
    used = [index for index, key in enumerate(keys) if key != ""]
    polygons = ZonePolygons.from_geometries(
        gdf.geometry.to_numpy()[used], [keys[index] for index in used], zone_keys=zone_keys
    )
    if raster_support is None:
        return polygons
    return polygons.clip_by_rect(
        float(raster_support.xmin),
        float(raster_support.ymin),
        float(raster_support.xmax),
        float(raster_support.ymax),
    )


def _code_field(field_record: Any, geology_cfg: Any) -> str:
    """The column holding the geological code: the BRGM one, or a custom source's."""
    if getattr(field_record, "source", "") in BRGM_SOURCES:
        return BRGM_CODE_FIELD
    for src in getattr(geology_cfg, "sources", []):
        if getattr(src, "source", "") == "custom" and getattr(src, "code_field", None):
            return src.code_field
    return BRGM_CODE_FIELD


__all__ = ["BRGM_CODE_FIELD", "BRGM_SOURCES", "build_geology_field"]
