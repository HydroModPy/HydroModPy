"""Site and recipe tables read as rows, every cell keeping where it came from.

The plan of a ``[sites]`` project reads two kinds of table: the site table
(``[sites] table``, one row per catchment) and the recipe table
(``[sites] recipes_table``, one row per recipe). Both are CSV, Parquet or
GeoPackage files whose columns are free and reach the configuration through
``[sites.bind]``. A :class:`TableRow` keeps the physical line of a text
file, so an error on a value can say ``sites.csv:37 column x_outlet``.

The site catalog of the workspace (``data/sites/catalog.csv``) is a table
too, with the fixed columns of :class:`~hydromodpy.core.site.SiteRow`:
:func:`table_from_site_rows` presents it the same way.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.site import SITE_ROW_COLUMNS, SiteRow

CSV_SUFFIXES = (".csv",)
PARQUET_SUFFIXES = (".parquet",)
GEOPACKAGE_SUFFIXES = (".gpkg",)

GEOMETRY_X_COLUMN = "geometry_x"
"""Column added to a GeoPackage of points: the easting of each geometry."""

GEOMETRY_Y_COLUMN = "geometry_y"
"""Column added to a GeoPackage of points: the northing of each geometry."""


class TableError(ConfigError):
    """A table cannot be read as rows of named cells."""


@dataclass(frozen=True, slots=True)
class CellOrigin:
    """Where one value of a case was written: a table, a row and a column."""

    table: str
    """The table as the user names it, relative to the project root."""

    line: int | None
    """Physical line in a text file; None for a binary table."""

    row: int
    """Data row, 1-based, the header left out."""

    column: str

    def __str__(self) -> str:
        where = (
            f"{self.table}:{self.line}" if self.line is not None else f"{self.table} row {self.row}"
        )
        return f"{where} column {self.column}"


@dataclass(frozen=True, slots=True)
class TableRow:
    """One row of a table."""

    index: int
    """Data row, 1-based."""

    line: int | None
    """Physical line of the row in a text file."""

    cells: Mapping[str, Any]

    def origin(self, table: Table, column: str) -> CellOrigin:
        """Return the origin of one cell of this row."""
        return CellOrigin(table=table.label, line=self.line, row=self.index, column=column)


@dataclass(frozen=True, slots=True)
class Table:
    """A table read whole: its columns and its rows."""

    path: Path
    label: str
    columns: tuple[str, ...]
    rows: tuple[TableRow, ...]


def is_empty_cell(value: Any) -> bool:
    """Return whether a cell holds nothing: ``None``, ``NaN`` or blank text."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


def read_table(path: Path, *, label: str) -> Table:
    """Read a CSV, Parquet or GeoPackage file as a table.

    A GeoPackage of points gains the columns :data:`GEOMETRY_X_COLUMN` and
    :data:`GEOMETRY_Y_COLUMN`. A missing file or an unknown suffix raises
    :class:`TableError` naming the file.
    """
    if not path.is_file():
        raise TableError(f"{label}: no such file ({path})")
    suffix = path.suffix.lower()
    if suffix in CSV_SUFFIXES:
        return _read_csv(path, label)
    if suffix in PARQUET_SUFFIXES:
        return _read_parquet(path, label)
    if suffix in GEOPACKAGE_SUFFIXES:
        return _read_geopackage(path, label)
    known = ", ".join((*CSV_SUFFIXES, *PARQUET_SUFFIXES, *GEOPACKAGE_SUFFIXES))
    raise TableError(f"{label}: a table is one of {known}, not {suffix or 'a file without suffix'}")


def _check_columns(label: str, columns: Sequence[str]) -> tuple[str, ...]:
    names = [str(name).strip() for name in columns]
    if any(not name for name in names):
        raise TableError(f"{label}: a column has no name")
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise TableError(f"{label}: column(s) named twice: {', '.join(duplicates)}")
    return tuple(names)


def _read_csv(path: Path, label: str) -> Table:
    rows: list[TableRow] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise TableError(f"{label}: the file is empty") from None
        columns = _check_columns(label, header)
        for index, record in enumerate(reader, start=1):
            if not record or all(not cell.strip() for cell in record):
                continue
            if len(record) != len(columns):
                raise TableError(
                    f"{label}:{reader.line_num}: {len(record)} cells for {len(columns)} columns"
                )
            cells = {name: cell.strip() for name, cell in zip(columns, record, strict=True)}
            rows.append(TableRow(index=index, line=reader.line_num, cells=cells))
    return Table(path=path, label=label, columns=columns, rows=tuple(rows))


def _read_parquet(path: Path, label: str) -> Table:
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    columns = _check_columns(label, table.column_names)
    rows = tuple(
        TableRow(index=index, line=None, cells=dict(record))
        for index, record in enumerate(table.to_pylist(), start=1)
    )
    return Table(path=path, label=label, columns=columns, rows=rows)


def _read_geopackage(path: Path, label: str) -> Table:
    import geopandas as gpd

    frame = gpd.read_file(path)
    geometry_name = frame.geometry.name if frame.geometry is not None else None
    columns = [name for name in frame.columns if name != geometry_name]
    records: list[dict[str, Any]] = []
    for _, record in frame.iterrows():
        cells = {name: record[name] for name in columns}
        geometry = record[geometry_name] if geometry_name is not None else None
        if geometry is not None and getattr(geometry, "geom_type", None) == "Point":
            cells[GEOMETRY_X_COLUMN] = float(geometry.x)
            cells[GEOMETRY_Y_COLUMN] = float(geometry.y)
        records.append(cells)
    if any(GEOMETRY_X_COLUMN in record for record in records):
        columns = [*columns, GEOMETRY_X_COLUMN, GEOMETRY_Y_COLUMN]
    checked = _check_columns(label, columns)
    rows = tuple(
        TableRow(index=index, line=None, cells=record)
        for index, record in enumerate(records, start=1)
    )
    return Table(path=path, label=label, columns=checked, rows=rows)


def table_from_site_rows(rows: Sequence[SiteRow], *, path: Path, label: str) -> Table:
    """Present the site catalog of the workspace as a table.

    The columns are those of :class:`~hydromodpy.core.site.SiteRow`, as
    :meth:`~hydromodpy.core.site.SiteRow.to_mapping` writes them. The line of
    a row is its line in the CSV file, the header on line 1.
    """
    table_rows = tuple(
        TableRow(index=index, line=index + 1, cells=row.to_mapping())
        for index, row in enumerate(rows, start=1)
    )
    return Table(path=path, label=label, columns=SITE_ROW_COLUMNS, rows=table_rows)


__all__ = [
    "CSV_SUFFIXES",
    "GEOMETRY_X_COLUMN",
    "GEOMETRY_Y_COLUMN",
    "GEOPACKAGE_SUFFIXES",
    "PARQUET_SUFFIXES",
    "CellOrigin",
    "Table",
    "TableError",
    "TableRow",
    "is_empty_cell",
    "read_table",
    "table_from_site_rows",
]
