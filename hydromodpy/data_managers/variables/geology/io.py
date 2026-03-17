"""
Input/output layer for geology sources.

Supported input sources:
- Raster grids (``.tif``, ``.tiff``)
- Vector polygons (``.shp``, ``.gpkg``, ``.geojson``, ``.json``)

Unified output contract:
- ``encoded_codes``: 2D integer grid (``0`` = nodata)
- ``encoded_to_zone``: ``int -> str`` mapping
- spatial metadata (``transform``, ``crs``)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.mask import mask as raster_mask
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

from hydromodpy.data_managers.variables.geology.processing import (
    apply_landsea_override,
    encode_numeric_raster,
    normalize_zone_key,
)


def infer_source_kind(source_path: str, requested_kind: str = "auto") -> str:
    """Infer geology source kind from extension when ``requested_kind='auto'``."""
    kind_key = str(requested_kind).strip().lower()
    if kind_key != "auto":
        return kind_key

    ext = Path(source_path).suffix.strip().lower()
    if ext in {".tif", ".tiff"}:
        return "raster"
    if ext in {".shp", ".gpkg", ".geojson", ".json"}:
        return "vector"
    raise ValueError(
        f"Cannot infer source kind from extension '{ext}'. "
        "Set source.kind explicitly to 'raster' or 'vector'."
    )


def resolve_data_path(data_path: str, *, config_path: str | Path | None = None) -> str:
    """Resolve one data path from either repository root or config-folder context."""
    raw = Path(str(data_path))
    if raw.is_absolute():
        return str(raw)

    repo_root = Path(__file__).resolve().parents[4]
    candidate_repo = (repo_root / raw).resolve()
    if candidate_repo.exists():
        return str(candidate_repo)

    if config_path is not None:
        cfg_parent = Path(config_path).resolve().parent
        candidate_cfg = (cfg_parent / raw).resolve()
        if candidate_cfg.exists():
            return str(candidate_cfg)

    return str(candidate_repo)


def load_vector_geology_dataframe(
    config: Mapping[str, Any],
    *,
    config_path: str | Path | None = None,
    zone_key_column: str = "zone_key",
):
    """Load vector geology source and return a GeoDataFrame ready for plotting."""
    import geopandas as gpd

    cfg = dict(config)
    source_cfg = dict(cfg["source"])
    if "path" not in source_cfg:
        raise KeyError("Missing required key source.path in geology config")

    source_path = resolve_data_path(str(source_cfg["path"]), config_path=config_path)
    source_kind = infer_source_kind(source_path, requested_kind=source_cfg.get("kind", "auto"))
    if source_kind != "vector":
        raise ValueError(
            f"Vector dataframe loading requires source.kind='vector' "
            f"(resolved kind: '{source_kind}')."
        )

    code_field = str(source_cfg.get("code_field", "")).strip()
    if code_field == "":
        raise KeyError("For vector source, 'code_field' is required")

    gdf = gpd.read_file(source_path)
    if gdf.empty:
        raise ValueError(f"Vector geology source has no geometry: {source_path}")
    if code_field not in gdf.columns:
        raise KeyError(f"Missing vector field '{code_field}' in {source_path}")

    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
    if gdf.empty:
        raise ValueError("Vector geology source has only empty geometries after filtering")

    clip_polygon_path = cfg.get("clip_polygon_path")
    if clip_polygon_path:
        clip_path = resolve_data_path(str(clip_polygon_path), config_path=config_path)
        clip_gdf = _load_clip_gdf(str(clip_path))
        if clip_gdf.crs is not None and gdf.crs is not None and clip_gdf.crs != gdf.crs:
            clip_gdf = clip_gdf.to_crs(gdf.crs)
        gdf = gpd.clip(gdf, clip_gdf)
        if gdf.empty:
            raise ValueError("No vector geology feature intersects clip polygon")

    zone_keys = gdf[code_field].astype(str).str.strip()
    gdf = gdf.loc[zone_keys != ""].copy()
    gdf[str(zone_key_column)] = zone_keys.loc[gdf.index].astype(str)
    if gdf.empty:
        raise ValueError(f"Field '{code_field}' produced no usable zone key")

    return {
        "gdf": gdf,
        "code_field": code_field,
        "field_id": str(cfg.get("id", "field_geology")),
        "source_path": str(source_path),
        "source_kind": str(source_kind),
    }


def _load_clip_gdf(clip_polygon_path: str):
    """Load and validate a clipping polygon layer as a GeoDataFrame."""
    import geopandas as gpd

    clip_gdf = gpd.read_file(clip_polygon_path)
    if clip_gdf.empty:
        raise ValueError(f"Clip polygon file has no geometry: {clip_polygon_path}")
    clip_gdf = clip_gdf[~clip_gdf.geometry.is_empty & clip_gdf.geometry.notna()]
    if clip_gdf.empty:
        raise ValueError(f"Clip polygon file has only empty geometries: {clip_polygon_path}")
    return clip_gdf


def _read_raster_codes(raster_path: str, *, clip_polygon_path: str | None = None):
    """Read one geology raster band and optionally clip it with a polygon mask."""
    with rasterio.open(raster_path) as src:
        if clip_polygon_path:
            clip_gdf = _load_clip_gdf(clip_polygon_path)
            if clip_gdf.crs is not None and src.crs is not None and clip_gdf.crs != src.crs:
                clip_gdf = clip_gdf.to_crs(src.crs)
            geoms = [geom.__geo_interface__ for geom in clip_gdf.geometry]
            data, transform = raster_mask(
                src, geoms, crop=True, filled=True,
                nodata=src.nodata if src.nodata is not None else np.nan,
            )
            raw = np.asarray(data[0], dtype=float)
        else:
            raw = np.asarray(src.read(1), dtype=float)
            transform = src.transform
        return raw, transform, src.crs, src.nodata


def _read_vector_codes(
    vector_path: str,
    *,
    code_field: str,
    reference_raster_path: str,
    clip_polygon_path: str | None = None,
    all_touched: bool = False,
):
    """Read geology polygons and rasterize them onto a reference raster grid."""
    import geopandas as gpd

    gdf = gpd.read_file(vector_path)
    if gdf.empty:
        raise ValueError(f"Vector geology source has no geometry: {vector_path}")
    if code_field not in gdf.columns:
        raise KeyError(f"Missing vector field '{code_field}' in {vector_path}")

    with rasterio.open(reference_raster_path) as ref:
        out_shape = (int(ref.height), int(ref.width))
        transform = ref.transform
        ref_crs = ref.crs

    if gdf.crs is not None and ref_crs is not None and gdf.crs != ref_crs:
        gdf = gdf.to_crs(ref_crs)

    if clip_polygon_path:
        clip_gdf = _load_clip_gdf(clip_polygon_path)
        if clip_gdf.crs is not None and gdf.crs is not None and clip_gdf.crs != gdf.crs:
            clip_gdf = clip_gdf.to_crs(gdf.crs)
        gdf = gpd.clip(gdf, clip_gdf)
        if gdf.empty:
            raise ValueError("No vector geology feature intersects clip polygon")

    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
    if gdf.empty:
        raise ValueError("Vector geology source has only empty geometries after filtering")

    zone_to_encoded: dict[str, int] = {}
    shapes = []
    for geom, raw_code in zip(gdf.geometry, gdf[code_field], strict=False):
        zone_key = normalize_zone_key(raw_code)
        if zone_key == "":
            continue
        if zone_key not in zone_to_encoded:
            zone_to_encoded[zone_key] = len(zone_to_encoded) + 1
        encoded = int(zone_to_encoded[zone_key])
        shapes.append((geom, encoded))
    if not shapes:
        raise ValueError("No valid vector geology feature with usable code")

    encoded = rasterize(
        shapes=shapes, out_shape=out_shape, transform=transform,
        fill=0, all_touched=bool(all_touched), dtype="int32",
    )
    encoded_to_zone = {int(v): str(k) for k, v in zone_to_encoded.items()}
    return encoded, encoded_to_zone, transform, ref_crs


def _grid_from_raster_support(raster_support):
    """Extract output grid geometry from one ``RasterSupport``-like object."""
    if raster_support is None:
        raise ValueError("raster_support is required")

    nrows = getattr(raster_support, "nrows", None)
    ncols = getattr(raster_support, "ncols", None)
    xmin = getattr(raster_support, "xmin", None)
    ymax = getattr(raster_support, "ymax", None)
    dx = getattr(raster_support, "dx", None)
    dy = getattr(raster_support, "dy", None)
    crs = getattr(raster_support, "crs", None)

    missing = [
        name for name, value in (
            ("nrows", nrows), ("ncols", ncols), ("xmin", xmin),
            ("ymax", ymax), ("dx", dx), ("dy", dy),
        ) if value is None
    ]
    if missing:
        raise ValueError(
            "RasterSupport is missing required grid metadata: " + ", ".join(missing)
        )

    out_shape = (int(nrows), int(ncols))
    transform = from_origin(float(xmin), float(ymax), float(dx), float(dy))
    return out_shape, transform, crs


def _read_raster_codes_on_raster_support(raster_path: str, *, raster_support):
    """Read and reproject a geology raster onto an explicit target raster support."""
    out_shape, target_transform, target_crs = _grid_from_raster_support(raster_support)
    with rasterio.open(raster_path) as src:
        source = np.asarray(src.read(1), dtype=float)
        nodata = src.nodata if src.nodata is not None else np.nan
        raw = np.full(out_shape, np.nan, dtype=float)
        reproject(
            source=source, destination=raw,
            src_transform=src.transform, src_crs=src.crs, src_nodata=src.nodata,
            dst_transform=target_transform,
            dst_crs=target_crs if target_crs is not None else src.crs,
            dst_nodata=np.nan, resampling=Resampling.nearest,
        )
        out_crs = target_crs if target_crs is not None else src.crs
    return raw, target_transform, out_crs, nodata


def _read_vector_codes_on_raster_support(
    vector_path: str, *, code_field: str, raster_support, all_touched: bool = False,
):
    """Read geology polygons and rasterize them on an explicit target raster support."""
    import geopandas as gpd

    gdf = gpd.read_file(vector_path)
    if gdf.empty:
        raise ValueError(f"Vector geology source has no geometry: {vector_path}")
    if code_field not in gdf.columns:
        raise KeyError(f"Missing vector field '{code_field}' in {vector_path}")

    out_shape, transform, target_crs = _grid_from_raster_support(raster_support)
    if gdf.crs is not None and target_crs is not None and gdf.crs != target_crs:
        gdf = gdf.to_crs(target_crs)

    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
    if gdf.empty:
        raise ValueError("Vector geology source has only empty geometries after filtering")

    zone_to_encoded: dict[str, int] = {}
    shapes = []
    for geom, raw_code in zip(gdf.geometry, gdf[code_field], strict=False):
        zone_key = normalize_zone_key(raw_code)
        if zone_key == "":
            continue
        if zone_key not in zone_to_encoded:
            zone_to_encoded[zone_key] = len(zone_to_encoded) + 1
        encoded = int(zone_to_encoded[zone_key])
        shapes.append((geom, encoded))
    if not shapes:
        raise ValueError("No valid vector geology feature with usable code")

    encoded = rasterize(
        shapes=shapes, out_shape=out_shape, transform=transform,
        fill=0, all_touched=bool(all_touched), dtype="int32",
    )
    encoded_to_zone = {int(v): str(k) for k, v in zone_to_encoded.items()}
    return encoded, encoded_to_zone, transform, target_crs


def _load_landsea_raster(
    landsea_path: str, *, target_shape, target_transform, target_crs,
    clip_polygon_path: str | None = None,
):
    """Load and reproject a land/sea raster onto the geology target grid."""
    with rasterio.open(landsea_path) as src:
        src_array = np.asarray(src.read(1), dtype=float)
        dst_array = np.full(tuple(target_shape), np.nan, dtype=float)
        reproject(
            source=src_array, destination=dst_array,
            src_transform=src.transform, src_crs=src.crs, src_nodata=src.nodata,
            dst_transform=target_transform, dst_crs=target_crs,
            dst_nodata=np.nan, resampling=Resampling.nearest,
        )

    if clip_polygon_path:
        clip_gdf = _load_clip_gdf(clip_polygon_path)
        if clip_gdf.crs is not None and target_crs is not None and clip_gdf.crs != target_crs:
            clip_gdf = clip_gdf.to_crs(target_crs)
        geoms = [geom.__geo_interface__ for geom in clip_gdf.geometry]
        clip_mask = rasterize(
            geoms, out_shape=tuple(target_shape), transform=target_transform,
            fill=0, default_value=1, dtype="uint8",
        )
        dst_array[clip_mask == 0] = np.nan
    return dst_array


def load_geology_encoded_grid(config: Mapping[str, Any]):
    """
    Load geology data from config and normalize it to one encoded grid contract.

    Returns dict with: ``encoded_codes``, ``encoded_to_zone``, ``transform``,
    ``crs``, ``source_kind``.
    """
    cfg = dict(config)
    source_cfg = dict(cfg["source"])
    source_path = str(source_cfg["path"])
    source_kind = infer_source_kind(source_path, requested_kind=source_cfg.get("kind", "auto"))
    clip_polygon_path = cfg.get("clip_polygon_path")

    if source_kind == "raster":
        raw, transform, crs, nodata = _read_raster_codes(
            source_path, clip_polygon_path=clip_polygon_path,
        )
        encoded, encoded_to_zone = encode_numeric_raster(raw, nodata_value=nodata)
    elif source_kind == "vector":
        encoded, encoded_to_zone, transform, crs = _read_vector_codes(
            source_path,
            code_field=str(source_cfg["code_field"]),
            reference_raster_path=str(source_cfg["reference_raster_path"]),
            clip_polygon_path=clip_polygon_path,
            all_touched=bool(source_cfg.get("all_touched", False)),
        )
    else:
        raise ValueError(f"Unsupported source kind '{source_kind}'")

    if not encoded_to_zone:
        raise ValueError("Geology source produced no valid zone code")

    landsea_cfg = dict(cfg.get("landsea", {}))
    if bool(landsea_cfg.get("enabled", False)):
        landsea = _load_landsea_raster(
            str(landsea_cfg["path"]),
            target_shape=encoded.shape, target_transform=transform,
            target_crs=crs, clip_polygon_path=clip_polygon_path,
        )
        encoded, encoded_to_zone = apply_landsea_override(
            encoded, encoded_to_zone=encoded_to_zone, landsea_array=landsea,
            sea_value=float(landsea_cfg.get("sea_value", 0.0)),
            override_zone_key=str(landsea_cfg.get("override_code", "1")),
        )

    return {
        "encoded_codes": np.asarray(encoded, dtype=np.int32),
        "encoded_to_zone": {int(k): str(v) for k, v in encoded_to_zone.items()},
        "transform": transform,
        "crs": crs,
        "source_kind": source_kind,
    }


def load_geology_encoded_grid_on_raster_support(
    config: Mapping[str, Any], *, raster_support,
):
    """Load geology data and normalize it on an explicit ``RasterSupport``."""
    cfg = dict(config)
    source_cfg = dict(cfg["source"])
    source_path = str(source_cfg["path"])
    source_kind = infer_source_kind(source_path, requested_kind=source_cfg.get("kind", "auto"))

    if source_kind == "raster":
        raw, transform, crs, nodata = _read_raster_codes_on_raster_support(
            source_path, raster_support=raster_support,
        )
        encoded, encoded_to_zone = encode_numeric_raster(raw, nodata_value=nodata)
    elif source_kind == "vector":
        encoded, encoded_to_zone, transform, crs = _read_vector_codes_on_raster_support(
            source_path,
            code_field=str(source_cfg["code_field"]),
            raster_support=raster_support,
            all_touched=bool(source_cfg.get("all_touched", False)),
        )
    else:
        raise ValueError(f"Unsupported source kind '{source_kind}'")

    if not encoded_to_zone:
        raise ValueError("Geology source produced no valid zone code")

    landsea_cfg = dict(cfg.get("landsea", {}))
    if bool(landsea_cfg.get("enabled", False)):
        landsea = _load_landsea_raster(
            str(landsea_cfg["path"]),
            target_shape=encoded.shape, target_transform=transform,
            target_crs=crs, clip_polygon_path=None,
        )
        encoded, encoded_to_zone = apply_landsea_override(
            encoded, encoded_to_zone=encoded_to_zone, landsea_array=landsea,
            sea_value=float(landsea_cfg.get("sea_value", 0.0)),
            override_zone_key=str(landsea_cfg.get("override_code", "1")),
        )

    return {
        "encoded_codes": np.asarray(encoded, dtype=np.int32),
        "encoded_to_zone": {int(k): str(v) for k, v in encoded_to_zone.items()},
        "transform": transform,
        "crs": crs,
        "source_kind": source_kind,
    }


def load_vector_geology_as_gpkg(
    vector_path: str | Path,
    *,
    code_field: str,
    bbox: tuple[float, float, float, float] | None = None,
    output_path: Path | None = None,
) -> Path:
    """
    Load a vector geology source, optionally crop to bbox, save as GeoPackage.

    Parameters
    ----------
    vector_path : path to the vector file
    code_field : attribute column containing geology codes
    bbox : (xmin, ymin, xmax, ymax) in the source CRS for cropping
    output_path : where to save the .gpkg (if None, returns the GeoDataFrame)

    Returns
    -------
    Path to the saved GeoPackage file.
    """
    import geopandas as gpd

    gdf = gpd.read_file(str(vector_path))
    if gdf.empty:
        raise ValueError(f"Vector geology source has no geometry: {vector_path}")
    if code_field not in gdf.columns:
        raise KeyError(f"Missing vector field '{code_field}' in {vector_path}")

    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()

    if bbox is not None:
        from shapely.geometry import box
        xmin, ymin, xmax, ymax = bbox
        bbox_geom = box(xmin, ymin, xmax, ymax)
        bbox_gdf = gpd.GeoDataFrame(geometry=[bbox_geom], crs=gdf.crs)
        gdf = gpd.clip(gdf, bbox_gdf)
        if gdf.empty:
            raise ValueError("No geology feature intersects the requested bbox")

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(str(output_path), driver="GPKG")

    return output_path
