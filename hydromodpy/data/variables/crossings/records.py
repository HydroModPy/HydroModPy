"""The shape every crossings source answers in, and how its pages are written.

One GeoDataFrame, whatever the provider: ``geometry`` plus four columns.

- ``kind``: one of :data:`~hydromodpy.data.variables.crossings.config.KINDS`.
- ``source``: the provider slug (``bdtopo``, ``roe``, ``custom``).
- ``name``: what the provider calls it, ``""`` when it says nothing.
- ``drop_m``: the drop of a weir or a dam in metres, NaN when unknown.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Final

from hydromodpy.data.variables.crossings.config import KINDS

if TYPE_CHECKING:  # pragma: no cover - typing only
    import geopandas as gpd

ATTRIBUTES: Final = ("kind", "source", "name", "drop_m")


def build(
    geometry: list,
    *,
    kind: list[str],
    source: str,
    name: list[str],
    drop_m: list[float],
    crs: str,
) -> gpd.GeoDataFrame:
    """The records of one source, columns in the fixed order."""
    import geopandas as gpd

    unknown = sorted(set(kind) - set(KINDS))
    if unknown:
        raise ValueError(f"crossings kind {unknown} is not one of {list(KINDS)}")
    return gpd.GeoDataFrame(
        {
            "kind": kind,
            "source": [source] * len(kind),
            "name": name,
            "drop_m": [float(value) for value in drop_m],
        },
        geometry=geometry,
        crs=crs,
    )


def empty(crs: str) -> gpd.GeoDataFrame:
    """No crossing, with the columns in place."""
    return build([], kind=[], source="", name=[], drop_m=[], crs=crs)


def append_pages(path: str | Path, pages: Iterable[gpd.GeoDataFrame], crs: str) -> int:
    """Write each page of records to the GeoPackage *path* as it comes, in *crs*.

    The file is created by the first page and appended to by the next ones, so a
    long answer is never held whole. Returns the number of records written;
    nothing is created when there is none.
    """
    written = 0
    for page in pages:
        if page.empty:
            continue
        moved = page.to_crs(crs)[[*ATTRIBUTES, "geometry"]]
        if Path(path).exists():
            moved.to_file(path, driver="GPKG", mode="a")
        else:
            # Lines and points share the file: an untyped layer holds both.
            moved.to_file(path, driver="GPKG", geometry_type="Unknown")
        written += len(moved)
    return written
