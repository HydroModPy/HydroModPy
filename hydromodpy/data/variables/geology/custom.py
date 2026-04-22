"""Custom geology data loaders.

Supports:
- SHP/GPKG: vector polygon files with geology codes in an attribute column
- TIF: raster files with numeric geology classes
- CSV: point data (x, y, geology_code) interpolated via Voronoi/nearest neighbor
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.data.contracts.spatial_field import FieldRecord


def load_custom_geology(
    source_cfg: Any,
    *,
    code_field: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    data_dir: Path | None = None,
) -> list[FieldRecord]:
    """Load custom geology data from a user-provided path.

    Parameters
    ----------
    source_cfg : source config with ``path`` attribute
    code_field : attribute column for geology codes (required for vector sources)
    bbox : optional bounding box for cropping
    data_dir : cache directory for processed outputs

    Returns
    -------
    List of FieldRecord pointing to the loaded/cached file.
    """
    path = Path(str(source_cfg.path)).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Custom geology path not found: {path}")

    # If directory, look for a single geology file inside
    if path.is_dir():
        path = _find_geology_file_in_dir(path)

    ext = path.suffix.strip().lower()

    if ext in (".shp", ".gpkg", ".geojson", ".json"):
        if not code_field:
            raise ValueError(
                f"'code_field' is required for custom vector geology source ({path.name}). "
                "Set it in [[data.geology.sources]] to the column containing geology codes."
            )
        return _load_custom_vector(path, code_field=code_field, bbox=bbox, data_dir=data_dir)
    elif ext in (".tif", ".tiff"):
        return _load_custom_raster(path, bbox=bbox, data_dir=data_dir)
    elif ext == ".csv":
        return _load_custom_csv(
            path,
            col_x=getattr(source_cfg, "col_x", "x"),
            col_y=getattr(source_cfg, "col_y", "y"),
            col_code=getattr(source_cfg, "col_code", "geology_code"),
            default_crs=getattr(source_cfg, "default_crs", "EPSG:2154"),
            bbox=bbox,
            data_dir=data_dir,
        )
    else:
        raise ValueError(
            f"Unsupported custom geology format: '{ext}'. "
            "Supported: .shp, .gpkg, .geojson, .tif, .csv"
        )


def _find_geology_file_in_dir(directory: Path) -> Path:
    """Find a single geology file in a directory."""
    for ext in (".gpkg", ".shp", ".geojson", ".tif", ".tiff", ".csv"):
        candidates = list(directory.glob(f"*{ext}"))
        if candidates:
            return candidates[0]
    raise FileNotFoundError(f"No geology file (SHP, GPKG, GeoJSON, TIF, CSV) found in {directory}")


def _load_custom_vector(
    path: Path,
    *,
    code_field: str,
    bbox: tuple | None = None,
    data_dir: Path | None = None,
) -> list[FieldRecord]:
    """Load a vector geology file, optionally crop, return as FieldRecord."""
    import geopandas as gpd

    gdf = gpd.read_file(str(path))
    if gdf.empty:
        raise ValueError(f"Custom vector geology file is empty: {path}")

    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()

    if code_field not in gdf.columns:
        raise KeyError(f"Column '{code_field}' not found in {path}. Available: {list(gdf.columns)}")

    crs = str(gdf.crs) if gdf.crs else "EPSG:2154"

    if bbox is not None:
        from shapely.geometry import box

        bbox_geom = box(*bbox)
        bbox_gdf = gpd.GeoDataFrame(geometry=[bbox_geom], crs=gdf.crs)
        gdf = gpd.clip(gdf, bbox_gdf)
        if gdf.empty:
            raise ValueError("No geology feature intersects bbox after clipping")

    actual_bbox = tuple(gdf.total_bounds) if not gdf.empty else bbox

    # Save as GeoPackage for uniformity
    if data_dir is not None:
        output_path = data_dir / f"geology_custom_{path.stem}.gpkg"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(str(output_path), driver="GPKG")
        data = output_path
    else:
        data = path

    return [
        FieldRecord(
            variable="geology",
            source="custom",
            unit="category",
            data=data,
            bbox=actual_bbox,
            crs=crs,
        )
    ]


def _load_custom_raster(
    path: Path,
    *,
    bbox: tuple | None = None,
    data_dir: Path | None = None,
) -> list[FieldRecord]:
    """Load a raster geology file as FieldRecord."""
    import rasterio

    with rasterio.open(str(path)) as src:
        bounds = src.bounds
        crs = str(src.crs) if src.crs else "EPSG:2154"
        actual_bbox = (bounds.left, bounds.bottom, bounds.right, bounds.top)

    return [
        FieldRecord(
            variable="geology",
            source="custom",
            unit="category",
            data=path,
            bbox=actual_bbox,
            crs=crs,
        )
    ]


def _load_custom_csv(
    path: Path,
    *,
    col_x: str = "x",
    col_y: str = "y",
    col_code: str = "geology_code",
    default_crs: str = "EPSG:2154",
    bbox: tuple | None = None,
    data_dir: Path | None = None,
) -> list[FieldRecord]:
    """Load CSV point geology data and interpolate via Voronoi tessellation.

    CSV format: x, y, geology_code
    Each point defines a zone. The Voronoi tessellation creates polygons
    assigning the nearest point's geology code to each spatial location.

    Parameters
    ----------
    path : CSV file path
    col_x, col_y : coordinate column names
    col_code : geology code column name
    default_crs : CRS for the point coordinates
    bbox : optional bounding box for the output
    data_dir : directory for saving the interpolated output
    """
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    from shapely import MultiPoint
    from shapely.geometry import box
    from shapely.ops import voronoi_diagram

    df = pd.read_csv(str(path))
    for col in (col_x, col_y, col_code):
        if col not in df.columns:
            raise KeyError(f"Column '{col}' not found in {path}. Available: {list(df.columns)}")

    df = df.dropna(subset=[col_x, col_y, col_code])
    if df.empty:
        raise ValueError(f"No valid rows in {path}")

    # Build point geometries
    from shapely.geometry import Point

    points = [Point(float(x), float(y)) for x, y in zip(df[col_x], df[col_y])]
    codes = df[col_code].astype(str).tolist()

    # Voronoi tessellation
    multi = MultiPoint(points)

    if bbox is not None:
        envelope = box(*bbox)
    else:
        # Use convex hull with buffer
        envelope = multi.convex_hull.buffer(
            max(multi.bounds[2] - multi.bounds[0], multi.bounds[3] - multi.bounds[1]) * 0.1
        )

    voronoi_polys = voronoi_diagram(multi, envelope=envelope)

    # Match Voronoi polygons to original points/codes
    records = []
    for poly in voronoi_polys.geoms:
        centroid = poly.centroid
        # Find nearest point
        dists = [centroid.distance(p) for p in points]
        nearest_idx = int(np.argmin(dists))
        records.append({"geometry": poly, col_code: codes[nearest_idx]})

    gdf = gpd.GeoDataFrame(records, crs=default_crs)

    # Clip to bbox
    if bbox is not None:
        bbox_gdf = gpd.GeoDataFrame(geometry=[box(*bbox)], crs=default_crs)
        gdf = gpd.clip(gdf, bbox_gdf)

    actual_bbox = tuple(gdf.total_bounds) if not gdf.empty else bbox

    # Save as GeoPackage
    if data_dir is not None:
        output_path = data_dir / f"geology_custom_{path.stem}_voronoi.gpkg"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(str(output_path), driver="GPKG")
        data = output_path
    else:
        data = path

    return [
        FieldRecord(
            variable="geology",
            source="custom",
            unit="category",
            data=data,
            bbox=actual_bbox,
            crs=default_crs,
        )
    ]
