"""Structured result from a variable manager's load() call."""

from __future__ import annotations

from dataclasses import dataclass, field

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.table import TableRecord
from hydromodpy.data.contracts.timeseries import PointRecord


@dataclass
class LoadResult:
    """Container separating point records, gridded fields, and tables.

    Returned by all variable managers so that the forcing/adapter layer
    can consume data without isinstance checks.
    """

    points: list[PointRecord] = field(default_factory=list)
    fields: list[FieldRecord] = field(default_factory=list)
    tables: list[TableRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.points) + len(self.fields) + len(self.tables)

    def __bool__(self) -> bool:
        return bool(self.points) or bool(self.fields) or bool(self.tables)

    @property
    def has_points(self) -> bool:
        return len(self.points) > 0

    @property
    def has_fields(self) -> bool:
        return len(self.fields) > 0

    @property
    def has_tables(self) -> bool:
        return len(self.tables) > 0

    @property
    def all_records(self) -> list:
        """Flat list of all points, fields, and tables."""
        return self.points + self.fields + self.tables
