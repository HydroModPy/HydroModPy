"""Gridded / spatial field contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

try:
    import xarray as xr
except ImportError:
    xr = None  # type: ignore[assignment]


@dataclass
class FieldRecord:
    """Gridded or vector spatial dataset (precipitation, ETP, geology, etc.).

    data is either an xarray Dataset in memory or a Path to a file on disk.
    """

    variable: str
    source: str
    unit: str
    data: Union["xr.Dataset", Path]
    bbox: tuple
    crs: str
    date_start: Optional[datetime] = None
    date_end: Optional[datetime] = None
    frequency: Optional[str] = None

    @property
    def is_static(self) -> bool:
        return self.date_start is None and self.date_end is None

    @property
    def is_file_reference(self) -> bool:
        return isinstance(self.data, (str, Path))
