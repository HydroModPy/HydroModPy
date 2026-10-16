"""The site catalog of a workspace: ``data/sites/catalog.csv``.

The catalog holds the sites a workspace declares, one :class:`SiteRow` per
line, in the columns of ``SITE_ROW_COLUMNS``. This module is the only reader
and writer of the file, and :func:`write_site_rows` the only writer of the
format anywhere. ``hmp site add`` and ``hmp site import`` add rows,
``hmp site ls`` and ``show`` read them, and a ``[sites]`` project without a
table reads the same file.

Two sites never share a name. An outlet closer than ``near_site_m`` (from
``workspace.toml``) to the outlet of a site declared under another name is
refused too: it is most likely the same catchment named twice. ``force``
replaces a site of the same name and accepts a close outlet.
"""

from __future__ import annotations

import csv
import math
import os
from collections.abc import Iterable, Sequence
from dataclasses import replace
from pathlib import Path

from hydromodpy.core.exceptions import ImportConflictError
from hydromodpy.core.site import SITE_ROW_COLUMNS, SiteRow
from hydromodpy.core.workspace.workspace_toml import near_site_m

SITE_CATALOG_RELPATH = "data/sites/catalog.csv"
"""Where the catalog sits, relative to the workspace root."""


class SiteConflictError(ImportConflictError):
    """A site to add takes a declared name, or an outlet too close to another site."""

    def __init__(self, conflicts: Sequence[str]) -> None:
        self.conflicts = tuple(conflicts)
        lines = "\n".join(f"  {line}" for line in self.conflicts)
        super().__init__(
            f"{len(self.conflicts)} site(s) not added, nothing written:\n{lines}\n"
            "Pass --force to replace a site of the same name and accept a close outlet."
        )


def catalog_path(workspace_root: Path) -> Path:
    """Return the path of the site catalog of a workspace."""
    return Path(workspace_root) / SITE_CATALOG_RELPATH


def read_catalog(workspace_root: Path) -> list[SiteRow]:
    """Return the sites of a workspace, in file order; an absent file has none."""
    path = catalog_path(workspace_root)
    if not path.is_file():
        return []
    rows: list[SiteRow] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for line, record in enumerate(reader, start=2):
            try:
                rows.append(SiteRow.from_mapping(record))
            except ValueError as exc:
                raise ValueError(f"{path}:{line}: {exc}") from exc
    return rows


def write_catalog(workspace_root: Path, rows: Iterable[SiteRow]) -> Path:
    """Write the sites of a workspace, replacing the file in one step."""
    return write_site_rows(catalog_path(workspace_root), rows)


def write_site_rows(path: Path, rows: Iterable[SiteRow]) -> Path:
    """Write site rows to *path* in the columns of a site table, replacing the file in one step.

    The one writer of the format: the workspace catalog and ``summary/catalog.csv``
    of a project both go through it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SITE_ROW_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {key: "" if value is None else value for key, value in row.to_mapping().items()}
            )
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


def nearest_site(
    rows: Iterable[SiteRow], *, x: float, y: float, crs: str | None
) -> tuple[SiteRow, float] | None:
    """Return the site whose outlet is closest to a point, with the distance in metres.

    The point is moved into the CRS of each row before measuring; a row
    without a CRS is read in the CRS of the point. A geographic CRS is
    measured on the ellipsoid. Rows without an outlet are skipped.
    """
    best: tuple[SiteRow, float] | None = None
    for row in rows:
        if row.x_outlet is None or row.y_outlet is None:
            continue
        distance = _distance_m(row, x=x, y=y, crs=crs)
        if best is None or distance < best[1]:
            best = (row, distance)
    return best


def add_sites(
    existing: Sequence[SiteRow],
    new: Iterable[SiteRow],
    *,
    near_site_m: float,
    force: bool = False,
) -> list[SiteRow]:
    """Return the catalog with ``new`` added, or raise listing every conflict.

    A new row of a declared name is a conflict, and so is an outlet closer
    than ``near_site_m`` to a site of another name (declared, or added just
    before in the same call). With ``force`` a row of the same name replaces
    the declared one in place and a close outlet is accepted.
    """
    merged = list(existing)
    position = {row.site: index for index, row in enumerate(merged)}
    added: set[str] = set()
    conflicts: list[str] = []
    for row in new:
        if row.site in added:
            conflicts.append(f"site {row.site}: listed twice in what is added")
            continue
        if row.site in position and not force:
            conflicts.append(f"site {row.site}: already declared in {SITE_CATALOG_RELPATH}")
            continue
        if row.x_outlet is not None and row.y_outlet is not None and not force:
            others = [other for other in merged if other.site != row.site]
            close = nearest_site(others, x=row.x_outlet, y=row.y_outlet, crs=row.crs)
            if close is not None and close[1] < near_site_m:
                conflicts.append(
                    f"site {row.site}: outlet {close[1]:.0f} m from site {close[0].site}, "
                    f"under near_site_m = {near_site_m:g} m"
                )
                continue
        added.add(row.site)
        if row.site in position:
            merged[position[row.site]] = row
        else:
            position[row.site] = len(merged)
            merged.append(row)
    if conflicts:
        raise SiteConflictError(conflicts)
    return merged


def declare_sites(
    workspace_root: Path, rows: Iterable[SiteRow], *, force: bool = False
) -> list[SiteRow]:
    """Add ``rows`` to the catalog of a workspace and return the catalog written.

    Reads ``[sites] near_site_m`` of ``workspace.toml``. Writes nothing when
    one row conflicts (see :func:`add_sites`).
    """
    root = Path(workspace_root)
    merged = add_sites(read_catalog(root), list(rows), near_site_m=near_site_m(root), force=force)
    write_catalog(root, merged)
    return merged


def with_tags(row: SiteRow, tags: Sequence[str]) -> SiteRow:
    """Return ``row`` with ``tags`` added after its own, without repeating one."""
    merged = tuple(dict.fromkeys([*row.tags, *tags]))
    return row if merged == row.tags else replace(row, tags=merged)


def _distance_m(row: SiteRow, *, x: float, y: float, crs: str | None) -> float:
    """Distance in metres from a point to the outlet of ``row``."""
    from pyproj import CRS, Geod, Transformer

    assert row.x_outlet is not None and row.y_outlet is not None
    target = row.crs or crs
    px, py = x, y
    if crs and target and CRS.from_user_input(crs) != CRS.from_user_input(target):
        transformer = Transformer.from_crs(crs, target, always_xy=True)
        px, py = transformer.transform(x, y)
    if target and CRS.from_user_input(target).is_geographic:
        _, _, distance = Geod(ellps="WGS84").inv(px, py, row.x_outlet, row.y_outlet)
        return float(abs(distance))
    return math.hypot(px - row.x_outlet, py - row.y_outlet)


__all__ = [
    "SITE_CATALOG_RELPATH",
    "SiteConflictError",
    "add_sites",
    "catalog_path",
    "declare_sites",
    "nearest_site",
    "read_catalog",
    "with_tags",
    "write_catalog",
    "write_site_rows",
]
