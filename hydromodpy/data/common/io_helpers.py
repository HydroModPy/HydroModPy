"""I/O helpers: CSV, Parquet, SHP/GPKG readers and filename conventions."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from hydromodpy.data.contracts.location import StationLocation

# Filename convention: TYPE_SOURCE_ID_YYYYMMDD_YYYYMMDD_FREQ.ext
FILENAME_PATTERN = re.compile(
    r"^(?P<type>[A-Za-z0-9]+)_(?P<source>[A-Za-z0-9]+)_(?P<id>.+?)_"
    r"(?P<start>\d{8})_(?P<end>\d{8})_(?P<freq>[A-Za-z0-9]+)\.(?P<ext>\w+)$"
)

# Location file: TYPE_SOURCE_LOC.ext
LOC_FILENAME_PATTERN = re.compile(
    r"^(?P<type>[A-Za-z0-9]+)_(?P<source>[A-Za-z0-9]+)_LOC\.(?P<ext>\w+)$"
)


def parse_chronicle_filename(filename: str) -> dict[str, str] | None:
    """Parse TYPE_SOURCE_ID_YYYYMMDD_YYYYMMDD_FREQ.ext, return groups or None."""
    m = FILENAME_PATTERN.match(filename)
    return m.groupdict() if m else None


def parse_loc_filename(filename: str) -> dict[str, str] | None:
    """Parse TYPE_SOURCE_LOC.ext, return groups or None."""
    m = LOC_FILENAME_PATTERN.match(filename)
    return m.groupdict() if m else None


def safe_file_token(value: str) -> str:
    """Replace non-alphanumeric chars with underscore for safe filenames."""
    return "".join(c if c.isalnum() else "_" for c in str(value))


def parse_datetime_column(series: pd.Series) -> pd.Series:
    """Parse datetime column (ISO strings or Unix timestamps ms/s)."""
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().any():
        dt_ms = pd.to_datetime(numeric, unit="ms", errors="coerce")
        dt_s = pd.to_datetime(numeric, unit="s", errors="coerce")
        out = dt_ms.where(dt_ms.notna(), dt_s)
        return out.where(out.notna(), pd.to_datetime(series, errors="coerce"))
    return pd.to_datetime(series, errors="coerce")


def read_locations_csv(
    path: Path,
    *,
    col_id: str = "id",
    col_x: str = "x",
    col_y: str = "y",
    col_crs: str = "crs",
    default_crs: str = "EPSG:4326",
) -> list[StationLocation]:
    """Read CSV location file into StationLocation list."""
    df = pd.read_csv(path)
    if col_id not in df.columns:
        raise ValueError(f"Location CSV {path} missing id column '{col_id}'. Columns: {list(df.columns)}")
    if col_x not in df.columns or col_y not in df.columns:
        raise ValueError(
            f"Location CSV {path} missing coordinate columns '{col_x}'/'{col_y}'. "
            f"Columns: {list(df.columns)}"
        )
    locations = []
    for _, row in df.iterrows():
        crs = str(row.get(col_crs, default_crs)) if col_crs in df.columns else default_crs
        extra = {k: v for k, v in row.items() if k not in (col_id, col_x, col_y, col_crs)}
        locations.append(
            StationLocation(
                id=str(row[col_id]),
                x=float(row[col_x]),
                y=float(row[col_y]),
                crs=crs,
                metadata=extra,
            )
        )
    return locations


def read_locations_vector(
    path: Path,
    *,
    col_id: str = "id",
) -> list[StationLocation]:
    """Read SHP/GeoPackage location file. CRS extracted from geometry."""
    gpd = _require_geopandas()
    gdf = gpd.read_file(path)
    if col_id not in gdf.columns:
        raise ValueError(f"Location file {path} missing id column '{col_id}'. Columns: {list(gdf.columns)}")
    crs_str = f"EPSG:{gdf.crs.to_epsg()}" if gdf.crs else "EPSG:4326"
    locations = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        extra = {k: v for k, v in row.items() if k not in (col_id, "geometry") and pd.notna(v)}
        locations.append(
            StationLocation(
                id=str(row[col_id]),
                x=float(geom.x),
                y=float(geom.y),
                crs=crs_str,
                metadata=extra,
            )
        )
    return locations


def read_locations(
    path: Path,
    *,
    col_id: str = "id",
    col_x: str = "x",
    col_y: str = "y",
    col_crs: str = "crs",
    default_crs: str = "EPSG:4326",
) -> list[StationLocation]:
    """Auto-detect format and read locations."""
    suffix = Path(path).suffix.lower()
    if suffix in (".shp", ".gpkg", ".geojson"):
        return read_locations_vector(path, col_id=col_id)
    return read_locations_csv(
        path, col_id=col_id, col_x=col_x, col_y=col_y,
        col_crs=col_crs, default_crs=default_crs,
    )


def read_timeseries_csv(
    path: Path,
    *,
    col_datetime: str = "datetime",
    col_value: str = "value",
    col_quality: str | None = "quality",
) -> pd.DataFrame:
    """Read chronicle CSV and normalize to [datetime, value] columns."""
    df = pd.read_csv(path)
    rename: dict[str, str] = {}
    if col_datetime != "datetime" and col_datetime in df.columns:
        rename[col_datetime] = "datetime"
    if col_value != "value" and col_value in df.columns:
        rename[col_value] = "value"
    if col_quality and col_quality != "quality" and col_quality in df.columns:
        rename[col_quality] = "quality"
    if rename:
        df = df.rename(columns=rename)

    if "datetime" not in df.columns:
        raise ValueError(
            f"Chronicle CSV {path} missing datetime column. "
            f"Expected '{col_datetime}'. Columns: {list(df.columns)}"
        )
    if "value" not in df.columns:
        raise ValueError(
            f"Chronicle CSV {path} missing value column. "
            f"Expected '{col_value}'. Columns: {list(df.columns)}"
        )

    df["datetime"] = parse_datetime_column(df["datetime"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df


def write_parquet(df: pd.DataFrame, path: Path) -> Path:
    """Write DataFrame to Parquet."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def read_parquet(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def _require_geopandas():
    try:
        import geopandas as gpd
        return gpd
    except ImportError as exc:
        raise ImportError("geopandas required for SHP/GeoPackage. pip install geopandas") from exc
