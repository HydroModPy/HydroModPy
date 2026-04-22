"""Gridded / spatial field contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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
    data: xr.Dataset | Path
    bbox: tuple
    crs: str
    date_start: datetime | None = None
    date_end: datetime | None = None
    frequency: str | None = None
    source_unit: str | None = None

    @property
    def is_static(self) -> bool:
        return self.date_start is None and self.date_end is None

    @property
    def is_file_reference(self) -> bool:
        return isinstance(self.data, (str, Path))

    @property
    def dataset(self) -> xr.Dataset:
        """Return the xarray Dataset, loading from disk if needed."""
        if isinstance(self.data, (str, Path)):
            if xr is None:
                raise ImportError("xarray is required to load FieldRecord data from disk")
            ds = xr.open_dataset(str(self.data))
            self.data = ds
            return ds
        return self.data
