"""Write a table of runs as Parquet, CSV and GeoPackage, the same cells in each.

A table of runs (``summary/by_case``, ``summary/by_site``) holds days,
instants, counts and paths. Each format gets the same cells: every date or
instant as ISO text, so a column has one type, counts kept integer where a
cell is missing (``Int64``), and every absolute path of a text cell written
from the project root (:func:`~hydromodpy.results.publication.redact`). Each
file is replaced only once written in full.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from hydromodpy.results.publication import redact
from hydromodpy.results.run.ranking import clean_cell

if TYPE_CHECKING:
    import pandas as pd

INTEGER_COLUMNS: Final[frozenset[str]] = frozenset(
    {"version", "attempt", "n_samples", "n_cases", "n_completed"}
)
"""Columns that hold a count, kept integer when a cell is missing."""


def write_table(frame: pd.DataFrame, target: Path, metadata: Mapping[str, str]) -> Path:
    import pyarrow as pa

    from hydromodpy.results.storage.parquet_io import write_table_atomic

    table = pa.Table.from_pandas(portable(frame), preserve_index=False)
    return write_table_atomic(table, target, kv_metadata=metadata)


def relative_paths(frame: pd.DataFrame, root: Path) -> pd.DataFrame:
    """Return the frame with every absolute path of a text cell written from the project root.

    A path outside the project becomes ``<absolute path>``. The summary is
    published as it is, and its Parquet tables are never rewritten on the way
    out. The full error of a failed case stays in its ``outcome.json``.
    """
    out = frame.copy()
    for column in out.columns:
        if out[column].dtype == object:
            out[column] = redact({"cells": list(out[column])}, project_root=root)["cells"]
    return out


def portable(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the frame with every date or instant as ISO text, so each column has one type.

    Counts stay integers where a cell is missing (``Int64``).
    """
    import pandas as pd

    out = frame.copy()
    for column in out.columns:
        values = out[column]
        if column in INTEGER_COLUMNS:
            out[column] = pd.to_numeric(values, errors="coerce").astype("Int64")
            continue
        if values.dtype == object or str(values.dtype).startswith("datetime"):
            out[column] = [_portable_cell(value) for value in values]
    return out


def _portable_cell(value: Any) -> Any:
    value = clean_cell(value)
    if value is None:
        return None
    if isinstance(value, datetime):
        return (value.astimezone(UTC) if value.tzinfo is not None else value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def write_csv(frame: pd.DataFrame, target: Path) -> Path:
    from hydromodpy.core.io.atomic_replace import staged_path

    with staged_path(target) as staged:
        portable(frame).to_csv(staged, index=False)
    return target


def in_one_crs(by_site: pd.DataFrame) -> pd.DataFrame:
    """Return ``by_site`` with every outlet in one CRS; several CRS give ``EPSG:4326``."""
    known = {
        str(crs)
        for crs, x in zip(by_site["crs"], by_site["x_outlet"], strict=True)
        if clean_cell(crs) is not None and clean_cell(x) is not None
    }
    if len(known) <= 1:
        return by_site
    from pyproj import Transformer

    out = by_site.copy()
    xs, ys = [], []
    for crs, x, y in zip(by_site["crs"], by_site["x_outlet"], by_site["y_outlet"], strict=True):
        if clean_cell(crs) is None or clean_cell(x) is None or clean_cell(y) is None:
            xs.append(None)
            ys.append(None)
            continue
        lon, lat = Transformer.from_crs(str(crs), "EPSG:4326", always_xy=True).transform(x, y)
        xs.append(lon)
        ys.append(lat)
    out["x_outlet"], out["y_outlet"], out["crs"] = xs, ys, "EPSG:4326"
    return out


def write_gpkg(map_frame: pd.DataFrame, target: Path, *, layer: str) -> Path:
    """Write the sites as points at their declared outlet."""
    import geopandas as gpd
    from shapely.geometry import Point

    from hydromodpy.core.io.atomic_replace import staged_path

    crs = next((str(c) for c in map_frame["crs"] if clean_cell(c) is not None), None)
    geometry = [
        Point(float(x), float(y))
        if clean_cell(x) is not None and clean_cell(y) is not None
        else None
        for x, y in zip(map_frame["x_outlet"], map_frame["y_outlet"], strict=True)
    ]
    frame = gpd.GeoDataFrame(portable(map_frame), geometry=geometry, crs=crs)
    with staged_path(target) as staged:
        frame.to_file(staged, driver="GPKG", layer=layer)
    return target


__all__ = [
    "INTEGER_COLUMNS",
    "in_one_crs",
    "portable",
    "relative_paths",
    "write_csv",
    "write_gpkg",
    "write_table",
]
