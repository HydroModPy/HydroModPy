"""Structured result from a variable manager's load() call."""

from __future__ import annotations

from dataclasses import dataclass, field

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord


@dataclass
class LoadResult:
    """Container separating point records from gridded fields.

    Returned by all variable managers so that the forcing/adapter layer
    can consume data without isinstance checks.
    """

    points: list[PointRecord] = field(default_factory=list)
    fields: list[FieldRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.points) + len(self.fields)

    def __bool__(self) -> bool:
        return bool(self.points) or bool(self.fields)

    @property
    def has_points(self) -> bool:
        return len(self.points) > 0

    @property
    def has_fields(self) -> bool:
        return len(self.fields) > 0

    @property
    def all_records(self) -> list:
        """Flat list of all records (backward compatibility)."""
        return self.points + self.fields
