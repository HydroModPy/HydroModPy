"""Shared process contracts used by HydroModPy internals.

This module holds the structural Protocols (``LoadResultProto``, ``FieldRecordProto``) used
to type spatial- and data-layer inputs without importing them.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LoadResultProto(Protocol):
    """Structural view of ``data.contracts.LoadResult`` used by the model.

    The binders of the model consume data-manager outputs through this
    Protocol so the model package never imports the data package.
    """

    points: list
    fields: list

    @property
    def has_points(self) -> bool: ...

    @property
    def has_fields(self) -> bool: ...


class FieldRecordProto(Protocol):
    """Structural view of ``data.contracts.FieldRecord``, one gridded dataset."""

    variable: str
    data: Any
    bbox: tuple
    crs: str
    date_start: Any
    date_end: Any
    metadata: dict[str, object]


__all__ = [
    "FieldRecordProto",
    "LoadResultProto",
]
