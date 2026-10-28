"""Build reduced DEM and geology inputs around one watershed.

This utility clips large regional datasets to a study-area envelope scaled
from the watershed bounds. It is intended to speed up domain/geographic runs.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import geopandas as gpd
import rasterio
from rasterio.windows import from_bounds
from shapely.geometry import box


def _scaled_bounds(
    bounds: tuple[float, float, float, float],
    *,
    area_factor: float,
) -> tuple[float, float, float, float]:
    """Scale a bounding box around its center by an area factor."""
    minx, miny, maxx, maxy = bounds
    if area_factor <= 0:
        raise ValueError("area_factor must be > 0")

    linear_factor = math.sqrt(area_factor)
    cx = 0.5 * (minx + maxx)
    cy = 0.5 * (miny + maxy)
    half_w = 0.5 * (maxx - minx) * linear_factor
    half_h = 0.5 * (maxy - miny) * linear_factor
    return (cx - half_w, cy - half_h, cx + half_w, cy + half_h)


def _clip_dem_to_bounds(
    dem_path: Path,
    out_dem_path: Path,
    bounds: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Clip one DEM raster to bounds (clamped to source extent)."""
    with rasterio.open(dem_path) as src:
        src_bounds = src.bounds
        minx = max(bounds[0], src_bounds.left)
        miny = max(bounds[1], src_bounds.bottom)
        maxx = min(bounds[2], src_bounds.right)
        maxy = min(bounds[3], src_bounds.top)

        if not (minx < maxx and miny < maxy):
            raise ValueError(
                "Requested clip bounds do not intersect DEM bounds. "
                f"clip={bounds}, dem={src_bounds}"
            )

        window = from_bounds(minx, miny, maxx, maxy, src.transform)
        window = window.round_offsets().round_lengths()
        data = src.read(window=window)
        transform = src.window_transform(window)
        profile = src.profile.copy()
        profile.update(
            width=int(window.width),
            height=int(window.height),
            transform=transform,
        )

        out_dem_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_dem_path, "w", **profile) as dst:
            dst.write(data)

    return (minx, miny, maxx, maxy)


def _clip_geology_to_bounds(
    geology_shp_path: Path,
    watershed_crs,
    out_geology_shp_path: Path,
    bounds: tuple[float, float, float, float],
) -> int:
    """Clip geology polygons to bounds in watershed CRS."""
    geology_gdf = gpd.read_file(geology_shp_path)
    if geology_gdf.crs != watershed_crs:
        geology_gdf = geology_gdf.to_crs(watershed_crs)

    clip_geom = gpd.GeoDataFrame(geometry=[box(*bounds)], crs=watershed_crs)
    clipped = gpd.clip(geology_gdf, clip_geom)
    if clipped.empty:
        raise ValueError("Clipped geology is empty; check source data and bounds.")

    out_geology_shp_path.parent.mkdir(parents=True, exist_ok=True)
    clipped.to_file(out_geology_shp_path)
    return int(len(clipped))


def build_reduced_inputs(
    *,
    watershed_shp_path: Path,
    dem_path: Path,
    geology_shp_path: Path,
    out_dir: Path,
    area_factor: float = 4.0,
) -> dict[str, object]:
    """Create reduced DEM and geology files around one watershed."""
    watershed_gdf = gpd.read_file(watershed_shp_path)
    if watershed_gdf.empty:
        raise ValueError("Watershed shapefile is empty.")

    watershed_union = watershed_gdf.geometry.union_all()
    scaled = _scaled_bounds(watershed_union.bounds, area_factor=area_factor)

    out_dem_path = out_dir / "dem" / "regional_dem_4x.tif"
    out_geology_shp_path = out_dir / "geology" / "GEO1M_4x.shp"

    dem_clip_bounds = _clip_dem_to_bounds(dem_path, out_dem_path, scaled)
    feature_count = _clip_geology_to_bounds(
        geology_shp_path,
        watershed_gdf.crs,
        out_geology_shp_path,
        dem_clip_bounds,
    )

    summary = {
        "watershed_shp": str(watershed_shp_path.resolve()),
        "source_dem": str(dem_path.resolve()),
        "source_geology_shp": str(geology_shp_path.resolve()),
        "area_factor": float(area_factor),
        "clip_bounds": [float(v) for v in dem_clip_bounds],
        "output_dem": str(out_dem_path.resolve()),
        "output_geology_shp": str(out_geology_shp_path.resolve()),
        "geology_feature_count": feature_count,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Clip DEM + geology around one watershed with a scaled bounding box "
            "(default area factor = 4)."
        )
    )
    parser.add_argument(
        "--watershed-shp",
        type=Path,
        required=True,
        help="Path to watershed shapefile (study area).",
    )
    parser.add_argument(
        "--dem",
        type=Path,
        required=True,
        help="Path to source DEM raster.",
    )
    parser.add_argument(
        "--geology-shp",
        type=Path,
        required=True,
        help="Path to source geology shapefile.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="Output directory under repository examples/data/.",
    )
    parser.add_argument(
        "--area-factor",
        type=float,
        default=4.0,
        help="Area scaling factor applied to watershed bounds (default: 4.0).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = build_reduced_inputs(
        watershed_shp_path=args.watershed_shp,
        dem_path=args.dem,
        geology_shp_path=args.geology_shp,
        out_dir=args.out_dir,
        area_factor=float(args.area_factor),
    )

    print(f"output_dem={summary['output_dem']}")
    print(f"output_geology_shp={summary['output_geology_shp']}")
    print(f"clip_bounds={summary['clip_bounds']}")
    print(f"geology_feature_count={summary['geology_feature_count']}")
    print(f"summary_json={str((Path(args.out_dir) / 'summary.json').resolve())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
