"""Build a Brittany-only geology dataset from the France-wide source.

This utility clips the global geology shapefile with the extent of the local
demo topography raster (`demo_top_bretagne_10km.tif`) and writes outputs to a
mirrored data structure under `examples/data/geology/`.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

import geopandas as gpd
import pandas as pd
import rasterio
from shapely.geometry import box


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "hydromodpy").is_dir():
            return parent
    return current.parents[0]


REPO_ROOT = _find_repo_root()

DEFAULT_SOURCE_SHP = REPO_ROOT / "data" / "France" / "geology" / "GEO1M.shp"
DEFAULT_SOURCE_CSV = REPO_ROOT / "data" / "France" / "geology" / "geology_K_dummy_demo.csv"
DEFAULT_SOURCE_DOC = REPO_ROOT / "data" / "France" / "geology" / "geology_K_dummy_demo_sources.md"
DEFAULT_REFERENCE_RASTER = Path(__file__).resolve().parent / "demo_top_bretagne_10km.tif"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "examples" / "data" / "geology"
DEFAULT_OUTPUT_SHP = "GEO1M_brittany.shp"
DEFAULT_OUTPUT_CSV = "geology_K_dummy_demo.csv"
DEFAULT_CODE_FIELD = "CODE_LEG"
DEFAULT_ZONE_KEY_COLUMN = "zone_key"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Clip France geology shapefile to Brittany demo extent and write a "
            "smaller mirrored dataset under examples/data/geology."
        )
    )
    parser.add_argument("--source-shp", default=str(DEFAULT_SOURCE_SHP))
    parser.add_argument("--source-csv", default=str(DEFAULT_SOURCE_CSV))
    parser.add_argument("--source-doc", default=str(DEFAULT_SOURCE_DOC))
    parser.add_argument("--reference-raster", default=str(DEFAULT_REFERENCE_RASTER))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--output-shp-name", default=DEFAULT_OUTPUT_SHP)
    parser.add_argument("--output-csv-name", default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--code-field", default=DEFAULT_CODE_FIELD)
    parser.add_argument("--zone-key-column", default=DEFAULT_ZONE_KEY_COLUMN)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files if they already exist.",
    )
    return parser.parse_args(argv)


def _require_file(path: Path, *, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


def _coerce_key_series(values: pd.Series) -> pd.Series:
    # Normalize keys as stripped strings so CSV and shapefile keys can be compared robustly.
    return values.astype(str).str.strip()


def main(argv=None) -> int:
    args = _parse_args(argv)
    source_shp = Path(args.source_shp).expanduser().resolve()
    source_csv = Path(args.source_csv).expanduser().resolve()
    source_doc = Path(args.source_doc).expanduser().resolve()
    reference_raster = Path(args.reference_raster).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_shp = output_dir / args.output_shp_name
    output_csv = output_dir / args.output_csv_name
    code_field = str(args.code_field)
    zone_key_column = str(args.zone_key_column)

    _require_file(source_shp, label="source shapefile")
    _require_file(source_csv, label="source CSV")
    _require_file(reference_raster, label="reference raster")
    if source_doc.exists():
        source_doc = source_doc.resolve()

    output_dir.mkdir(parents=True, exist_ok=True)

    if output_shp.exists() and not args.overwrite:
        raise FileExistsError(
            f"Output shapefile already exists: {output_shp}. Use --overwrite to replace it."
        )
    if output_csv.exists() and not args.overwrite:
        raise FileExistsError(
            f"Output CSV already exists: {output_csv}. Use --overwrite to replace it."
        )

    # Remove previous shapefile sidecars when overwriting.
    if args.overwrite:
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".fix"):
            sidecar = output_shp.with_suffix(ext)
            if sidecar.exists():
                sidecar.unlink()

    with rasterio.open(reference_raster) as src:
        raster_bounds = src.bounds
        raster_crs = src.crs
    if raster_crs is None:
        raise ValueError(f"Reference raster has no CRS: {reference_raster}")

    clip_box = box(raster_bounds.left, raster_bounds.bottom, raster_bounds.right, raster_bounds.top)
    clip_gdf = gpd.GeoDataFrame({"geometry": [clip_box]}, crs=raster_crs)

    gdf = gpd.read_file(source_shp)
    if gdf.empty:
        raise ValueError(f"Source shapefile has no features: {source_shp}")
    if code_field not in gdf.columns:
        raise KeyError(f"Missing code field '{code_field}' in {source_shp}")

    if gdf.crs is None:
        raise ValueError(f"Source shapefile has no CRS: {source_shp}")
    if gdf.crs != clip_gdf.crs:
        clip_gdf = clip_gdf.to_crs(gdf.crs)

    bbox_geom = clip_gdf.geometry.iloc[0]
    subset = gdf[gdf.intersects(bbox_geom)].copy()
    if subset.empty:
        raise ValueError("No geology features intersect the reference raster extent")
    clipped = gpd.clip(subset, clip_gdf, keep_geom_type=False)
    clipped = clipped[~clipped.geometry.is_empty].copy()
    if clipped.empty:
        raise ValueError("Clip step produced an empty geology subset")

    clipped.to_file(output_shp)

    csv_df = pd.read_csv(source_csv)
    if zone_key_column not in csv_df.columns:
        raise KeyError(f"Missing '{zone_key_column}' in CSV {source_csv}")

    clipped_keys = set(_coerce_key_series(clipped[code_field]))
    csv_keys = _coerce_key_series(csv_df[zone_key_column])
    csv_subset = csv_df.loc[csv_keys.isin(clipped_keys)].copy()
    if csv_subset.empty:
        raise ValueError(
            "No CSV rows match clipped geology keys. "
            f"Check code field '{code_field}' and zone key column '{zone_key_column}'."
        )
    csv_subset.to_csv(output_csv, index=False)

    if source_doc.exists():
        shutil.copyfile(source_doc, output_dir / source_doc.name)

    print(f"source_features={len(gdf)}")
    print(f"subset_features={len(subset)}")
    print(f"clipped_features={len(clipped)}")
    print(f"source_csv_rows={len(csv_df)}")
    print(f"subset_csv_rows={len(csv_subset)}")
    print(f"output_shp={output_shp}")
    print(f"output_csv={output_csv}")
    if source_doc.exists():
        print(f"output_doc={output_dir / source_doc.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
