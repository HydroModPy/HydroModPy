"""
Input/output layer for geology sources used by the `GeologyField` case.

Purpose
-------
This module reads external geology data and converts it to one unified internal
representation that the rest of the field framework can consume.

Supported input sources
-----------------------
- Raster grids (`.tif`, `.tiff`)
- Vector polygons (`.shp`, `.gpkg`, `.geojson`, `.json`)

Unified output contract
-----------------------
No matter the source type, the main loader returns:
- `encoded_codes`: 2D integer grid
  - `0` means nodata / no usable class
  - strictly positive integers represent geology classes
- `encoded_to_zone`: dictionary `int -> str`
  mapping encoded integers to normalized zone keys
  (for example `{1: "granite", 2: "micaschists"}`)
- spatial metadata (`transform`, `crs`, optional nodata context)

Why this design
---------------
Downstream code should not care whether geology came from raster or vector.
With this contract:
- `GeologyField` can sample zone keys consistently on any mesh.
- `FieldParam(kind="heterogeneous", values_by_key=...)` can assign physical
  values by key independently of file format.

High-level processing steps
---------------------------
1) Detect source kind (`infer_source_kind`) unless explicitly provided.
2) Read raster or vector source.
3) (Optional) clip to a polygon mask.
4) Build encoded classes and key mapping.
5) (Optional) apply land/sea override to force a specific zone in sea pixels.
6) Return a single normalized payload for `GeologyField`.

Dependencies
------------
- Core path relies on `numpy` + `rasterio`.
- `geopandas` is imported only inside vector/clip helpers, so raster-only
  workflows do not require it at import time.

Non-goals
---------
- No calibration logic.
- No mesh discretization logic.
- No parameter value assignment (handled later by `FieldParam`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.mask import mask as raster_mask
from rasterio.warp import Resampling, reproject

from hydromodpy.field.cases.geology.geology_processing import (
    apply_landsea_override,
    encode_numeric_raster,
    normalize_zone_key,
)


def infer_source_kind(source_path: str, requested_kind: str = "auto") -> str:
    """
    Infer geology source kind from extension when `requested_kind='auto'`.

    Example
    -------
    infer_source_kind("foo.tif", "auto") -> "raster"
    infer_source_kind("foo.shp", "auto") -> "vector"
    infer_source_kind("foo.any", "raster") -> "raster"
    """
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
    """
    Resolve one data path from either repository root or config-folder context.

    Resolution order
    ----------------
    1) absolute path (returned as-is),
    2) repository-root relative path,
    3) config-file folder relative path (if `config_path` is provided),
    4) fallback to repository-root candidate string.
    """
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
    """
    Load vector geology source and return a GeoDataFrame ready for plotting.

    Parameters
    ----------
    config : Mapping[str, Any]
        Validated geology configuration mapping.
    config_path : str | Path | None, optional
        Path to the TOML file. Used to resolve relative data paths.
    zone_key_column : str, default="zone_key"
        Name of the output column storing normalized geology keys.

    Returns
    -------
    dict[str, Any]
        Dictionary with:
        - `gdf`: filtered GeoDataFrame with valid geometries and zone keys,
        - `code_field`: source attribute field used for geology classes,
        - `field_id`: geology field identifier,
        - `source_path`: resolved source path,
        - `source_kind`: resolved source kind (`"vector"` here).
    """
    # Local import keeps geopandas optional for non-vector workflows.
    import geopandas as gpd

    cfg = dict(config)
    source_cfg = dict(cfg["source"])
    if "path" not in source_cfg:
        raise KeyError("Missing required key source.path in geology config")

    source_path = resolve_data_path(str(source_cfg["path"]), config_path=config_path)
    source_kind = infer_source_kind(source_path, requested_kind=source_cfg.get("kind", "auto"))
    if source_kind != "vector":
        raise ValueError(
            "Vector dataframe loading requires source.kind='vector' "
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
    """
    Load and validate a clipping polygon layer as a GeoDataFrame.

    Parameters
    ----------
    clip_polygon_path : str
        Path to the vector file used to clip raster/vector geology inputs.

    Returns
    -------
    geopandas.GeoDataFrame
        Non-empty GeoDataFrame with valid (non-empty, non-null) geometries.

    Raises
    ------
    ValueError
        If the input file contains no features, or only empty/null geometries.

    Notes
    -----
    `geopandas` is imported locally to keep it as an optional dependency for
    workflows that do not need clipping or vector processing.
    """
    # Local import so raster-only workflows can run without geopandas installed.
    import geopandas as gpd

    # Read polygon features from disk.
    clip_gdf = gpd.read_file(clip_polygon_path)

    # Immediate guard: no rows/features at all.
    if clip_gdf.empty:
        raise ValueError(f"Clip polygon file has no geometry: {clip_polygon_path}")

    # Keep only usable geometries:
    # - drop empty shapes,
    # - drop missing values (None/NaN geometries).
    clip_gdf = clip_gdf[~clip_gdf.geometry.is_empty & clip_gdf.geometry.notna()]

    # Guard after filtering: file existed but no usable geometry remains.
    if clip_gdf.empty:
        raise ValueError(f"Clip polygon file has only empty geometries: {clip_polygon_path}")
    return clip_gdf


def _read_raster_codes(
    raster_path: str,
    *,
    clip_polygon_path: str | None = None,
):
    """
    Read one geology raster band and optionally clip it with a polygon mask.

    Parameters
    ----------
    raster_path : str
        Path to the raster source file. The first band is read.
    clip_polygon_path : str | None, optional
        Optional path to a polygon layer used to clip/crop the raster.
        If provided:
        - polygon geometries are loaded/validated,
        - polygon CRS is reprojected to raster CRS when needed,
        - output is cropped to the polygon extent.

    Returns
    -------
    tuple[np.ndarray, object, object, object]
        `(raw, transform, crs, nodata)` where:
        - `raw` is the first band as a float array,
        - `transform` is the affine transform of returned raster grid
          (updated when clipping is applied),
        - `crs` is raster CRS metadata,
        - `nodata` is source nodata value from the input raster.

    Notes
    -----
    - Output array is converted to float for consistent downstream handling.
    - If source nodata is missing and clipping is requested, clipped-out pixels
      are filled with `NaN`.
    """
    # Open raster once and keep metadata (`crs`, `transform`, `nodata`) from
    # the same dataset handle to avoid inconsistencies.
    with rasterio.open(raster_path) as src:
        # Optional clip path: crop raster to polygon geometry footprint.
        if clip_polygon_path:
            # Load and validate clip geometries (non-empty, non-null).
            clip_gdf = _load_clip_gdf(clip_polygon_path)

            # Reproject clip polygons to raster CRS if both are defined and differ.
            if clip_gdf.crs is not None and src.crs is not None and clip_gdf.crs != src.crs:
                clip_gdf = clip_gdf.to_crs(src.crs)

            # Convert GeoPandas geometries to GeoJSON-like mappings expected by rasterio.mask.
            geoms = [geom.__geo_interface__ for geom in clip_gdf.geometry]

            # Mask + crop raster on polygon area.
            # `filled=True` writes nodata outside polygons.
            # `nodata` fallback to NaN when source nodata is missing.
            data, transform = raster_mask(
                src,
                geoms,
                crop=True,
                filled=True,
                nodata=src.nodata if src.nodata is not None else np.nan,
            )

            # `raster_mask` returns shape (bands, rows, cols); keep first band only.
            raw = np.asarray(data[0], dtype=float)
        else:
            # No clip: read first band as-is and keep original transform.
            raw = np.asarray(src.read(1), dtype=float)
            transform = src.transform

        # Return data + spatial metadata in a stable tuple contract.
        return raw, transform, src.crs, src.nodata


def _read_vector_codes(
    vector_path: str,
    *,
    code_field: str,
    reference_raster_path: str,
    clip_polygon_path: str | None = None,
    all_touched: bool = False,
):
    """
    Read geology polygons and rasterize them onto a reference raster grid.

    Parameters
    ----------
    vector_path : str
        Path to the vector geology file (polygons).
    code_field : str
        Name of the attribute column containing geology classes/codes.
        Values are normalized to zone keys with `normalize_zone_key`.
    reference_raster_path : str
        Path to the raster used as spatial reference for rasterization.
        It defines output resolution, shape, transform, and CRS.
    clip_polygon_path : str | None, optional
        Optional polygon file to clip vector features before rasterization.
    all_touched : bool, default=False
        Rasterization mode passed to `rasterio.features.rasterize`:
        - `False`: only pixels whose center falls in polygon are burned,
        - `True`: any pixel touched by polygon boundary is burned.

    Returns
    -------
    tuple[np.ndarray, dict[int, str], object, object]
        `(encoded, encoded_to_zone, transform, crs)` where:
        - `encoded` is a 2D `int32` array (`0` for unassigned),
        - `encoded_to_zone` maps encoded integers to normalized zone keys,
        - `transform` and `crs` come from the reference raster.

    Raises
    ------
    ValueError
        If input has no usable geometries, if clipping removes all features,
        or if no valid code can be extracted.
    KeyError
        If `code_field` is missing in the vector file.

    Notes
    -----
    Encoded IDs are assigned sequentially in first-seen order of normalized
    zone keys (1, 2, 3, ...). This keeps the output compact and deterministic
    for a given feature ordering.
    """
    # Local import keeps geopandas optional for workflows that only use rasters.
    import geopandas as gpd

    # Load vector features and perform early structural validations.
    gdf = gpd.read_file(vector_path)
    if gdf.empty:
        raise ValueError(f"Vector geology source has no geometry: {vector_path}")
    if code_field not in gdf.columns:
        raise KeyError(f"Missing vector field '{code_field}' in {vector_path}")

    # Read reference raster metadata to define output grid geometry.
    # Vector polygons will be burned on this exact grid.
    with rasterio.open(reference_raster_path) as ref:
        out_shape = (int(ref.height), int(ref.width))
        transform = ref.transform
        ref_crs = ref.crs

    # Harmonize CRS before any spatial operation.
    if gdf.crs is not None and ref_crs is not None and gdf.crs != ref_crs:
        gdf = gdf.to_crs(ref_crs)

    # Optional clip to reduce domain to the area of interest.
    if clip_polygon_path:
        clip_gdf = _load_clip_gdf(clip_polygon_path)
        if clip_gdf.crs is not None and gdf.crs is not None and clip_gdf.crs != gdf.crs:
            clip_gdf = clip_gdf.to_crs(gdf.crs)
        gdf = gpd.clip(gdf, clip_gdf)
        if gdf.empty:
            raise ValueError("No vector geology feature intersects clip polygon")

    # Keep only valid geometries before encoding/rasterization.
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
    if gdf.empty:
        raise ValueError("Vector geology source has only empty geometries after filtering")

    # Build two things simultaneously:
    # - a compact encoding map: zone key -> integer code,
    # - `shapes` list for rasterization: (geometry, encoded_int).
    zone_to_encoded: dict[str, int] = {}
    shapes = []
    for geom, raw_code in zip(gdf.geometry, gdf[code_field], strict=False):
        # Normalize raw attribute (string/number/etc.) into one clean zone key.
        zone_key = normalize_zone_key(raw_code)
        # Skip empty/invalid keys after normalization.
        if zone_key == "":
            continue
        # Assign a new integer code on first encounter of each key.
        if zone_key not in zone_to_encoded:
            zone_to_encoded[zone_key] = len(zone_to_encoded) + 1
        encoded = int(zone_to_encoded[zone_key])
        shapes.append((geom, encoded))
    if not shapes:
        raise ValueError("No valid vector geology feature with usable code")

    # Rasterize polygons onto the reference grid.
    # Unassigned pixels remain at 0.
    encoded = rasterize(
        shapes=shapes,
        out_shape=out_shape,
        transform=transform,
        fill=0,
        all_touched=bool(all_touched),
        dtype="int32",
    )
    # Convert key->int map to int->key map for downstream lookup.
    encoded_to_zone = {int(v): str(k) for k, v in zone_to_encoded.items()}
    return encoded, encoded_to_zone, transform, ref_crs


def _load_landsea_raster(
    landsea_path: str,
    *,
    target_shape,
    target_transform,
    target_crs,
    clip_polygon_path: str | None = None,
):
    """
    Load and reproject a land/sea raster onto the geology target grid.
    """
    with rasterio.open(landsea_path) as src:
        src_array = np.asarray(src.read(1), dtype=float)
        dst_array = np.full(tuple(target_shape), np.nan, dtype=float)
        reproject(
            source=src_array,
            destination=dst_array,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=target_transform,
            dst_crs=target_crs,
            dst_nodata=np.nan,
            resampling=Resampling.nearest,
        )

    if clip_polygon_path:
        clip_gdf = _load_clip_gdf(clip_polygon_path)
        if clip_gdf.crs is not None and target_crs is not None and clip_gdf.crs != target_crs:
            clip_gdf = clip_gdf.to_crs(target_crs)
        geoms = [geom.__geo_interface__ for geom in clip_gdf.geometry]
        clip_mask = rasterize(
            geoms,
            out_shape=tuple(target_shape),
            transform=target_transform,
            fill=0,
            default_value=1,
            dtype="uint8",
        )
        dst_array[clip_mask == 0] = np.nan
    return dst_array


def load_geology_encoded_grid(
    config: Mapping[str, Any],
):
    """
    Load geology data from config and normalize it to one encoded grid contract.

    Parameters
    ----------
    config : Mapping[str, Any]
        Validated geology configuration mapping. Expected keys include:
        - `source.path` (mandatory),
        - `source.kind` (`"auto"`, `"raster"`, `"vector"`),
        - vector-only keys when needed (`code_field`, `reference_raster_path`),
        - optional `clip_polygon_path`,
        - optional `landsea` block for sea override.

    Returns
    -------
    dict[str, Any]
        Normalized payload with:
        - `encoded_codes`: 2D `int32` array (`0` = nodata/unassigned),
        - `encoded_to_zone`: mapping `encoded_int -> zone_key`,
        - `transform`: affine transform of encoded grid,
        - `crs`: coordinate reference system metadata,
        - `source_kind`: resolved source kind (`"raster"` or `"vector"`).

    Raises
    ------
    ValueError
        If source kind is unsupported, or if no valid geology code is found.

    Notes
    -----
    The function enforces one uniform representation for downstream steps
    (`GeologyField.zone_id`, `GeologyField.on_mesh`) regardless of original
    input format.

    Example
    -------
    payload = load_geology_encoded_grid(config)
    codes = payload["encoded_codes"]      # 2D int array
    zones = payload["encoded_to_zone"]    # {1: "granite", ...}
    """
    # Defensive copy to avoid mutating caller-owned mappings.
    cfg = dict(config)
    source_cfg = dict(cfg["source"])

    # Extract source path and resolve effective source kind.
    source_path = str(source_cfg["path"])
    source_kind = infer_source_kind(source_path, requested_kind=source_cfg.get("kind", "auto"))

    # Optional clip polygon used in both raster and vector branches.
    clip_polygon_path = cfg.get("clip_polygon_path")

    # 1) Read source and convert it to the common encoded representation:
    #    - encoded integer grid (`encoded`),
    #    - encoded integer -> zone key dictionary (`encoded_to_zone`),
    #    - spatial metadata (`transform`, `crs`).
    if source_kind == "raster":
        # Raster branch: read one numeric band then encode unique values.
        raw, transform, crs, nodata = _read_raster_codes(
            source_path,
            clip_polygon_path=clip_polygon_path,
        )
        encoded, encoded_to_zone = encode_numeric_raster(raw, nodata_value=nodata)
    elif source_kind == "vector":
        # Vector branch: rasterize polygons onto a reference grid.
        encoded, encoded_to_zone, transform, crs = _read_vector_codes(
            source_path,
            code_field=str(source_cfg["code_field"]),
            reference_raster_path=str(source_cfg["reference_raster_path"]),
            clip_polygon_path=clip_polygon_path,
            all_touched=bool(source_cfg.get("all_touched", False)),
        )
    else:
        raise ValueError(f"Unsupported source kind '{source_kind}'")

    # Hard validation: at least one usable zone must exist.
    if not encoded_to_zone:
        raise ValueError("Geology source produced no valid zone code")

    # 2) Optional post-processing: override sea pixels with one dedicated zone.
    #    This can enforce a coastal/ocean class consistently across the grid.
    landsea_cfg = dict(cfg.get("landsea", {}))
    if bool(landsea_cfg.get("enabled", False)):
        # Load/reproject land-sea raster to the exact same grid as `encoded`.
        landsea = _load_landsea_raster(
            str(landsea_cfg["path"]),
            target_shape=encoded.shape,
            target_transform=transform,
            target_crs=crs,
            clip_polygon_path=clip_polygon_path,
        )

        # Apply override and update both grid values and mapping dictionary.
        encoded, encoded_to_zone = apply_landsea_override(
            encoded,
            encoded_to_zone=encoded_to_zone,
            landsea_array=landsea,
            sea_value=float(landsea_cfg.get("sea_value", 0.0)),
            override_zone_key=str(landsea_cfg.get("override_code", "1")),
        )

    # Final normalization of output types for stable downstream behavior.
    return {
        "encoded_codes": np.asarray(encoded, dtype=np.int32),
        "encoded_to_zone": {int(k): str(v) for k, v in encoded_to_zone.items()},
        "transform": transform,
        "crs": crs,
        "source_kind": source_kind,
    }
