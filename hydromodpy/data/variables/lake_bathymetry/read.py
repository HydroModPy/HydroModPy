"""Lake bathymetry reader matching raster paths to lake ids."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def lake_bathymetry(
    result: Any,
    lake_ids: list[str],
) -> dict[str, Path]:
    """Match each bathymetry raster path to a lake id.

    A single record feeds the single declared lake. With several records or
    lakes, a record is matched to a lake id when its file stem contains that id
    (e.g. ``lake_bathymetry_custom_lac0.tif`` -> ``lac0``).
    """
    if result is None:
        return {}
    records = list(getattr(result, "fields", result) or [])
    paths = [
        Path(getattr(rec, "data", rec))
        for rec in records
        if getattr(rec, "data", rec) is not None and str(getattr(rec, "data", rec)).strip()
    ]
    bathy_by_lake: dict[str, Path] = {}
    if len(paths) == 1 and len(lake_ids) == 1:
        bathy_by_lake[lake_ids[0]] = paths[0]
        return bathy_by_lake
    for path in paths:
        stem = path.stem
        for lake_id in lake_ids:
            if lake_id in stem:
                bathy_by_lake[lake_id] = path
    return bathy_by_lake
