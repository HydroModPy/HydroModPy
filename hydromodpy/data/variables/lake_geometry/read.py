"""Lake geometry reader extracting footprint polygons from loaded data."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry


def lake_polygons(
    result: Any,
    lake_ids: list[str],
) -> dict[str, BaseGeometry]:
    """Match each lake-geometry record's footprint polygon to a lake id.

    The input `result` may be a LoadResult with a `.fields` sequence of
    FieldRecord objects, or an iterable of records directly.
    """
    import geopandas as gpd

    if result is None:
        return {}
    records = list(getattr(result, "fields", result) or [])
    if not records:
        return {}

    polygons_by_lake: dict[str, BaseGeometry] = {}
    for record in records:
        data_path = getattr(record, "data", record)
        if not data_path:
            continue
        gdf = gpd.read_parquet(str(data_path))
        if gdf.empty:
            continue
        if "lake_id" in gdf.columns:
            for lake_id, group in gdf.groupby("lake_id"):
                polygons_by_lake[str(lake_id)] = group.union_all()
        elif len(lake_ids) == 1:
            polygons_by_lake[lake_ids[0]] = gdf.union_all()
    return polygons_by_lake
