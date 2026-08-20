"""Tabular (non-timeseries, non-gridded) dataset contract.

A :class:`TableRecord` carries an arbitrary-shape table that is neither a
``[datetime, value]`` time series (see :class:`PointRecord`) nor a gridded
spatial field (see :class:`FieldRecord`). The motivating case is a lake
stage-volume-area abacus (``ModflowUtllaktab``), whose rows are indexed by
stage rather than by time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


@dataclass
class TableRecord:
    """Tabular dataset produced by a variable manager.

    ``data`` is either a :class:`pandas.DataFrame` held in memory or a
    :class:`pathlib.Path` to a Parquet file on disk. ``table_id`` reuses the
    station-id convention so a multi-lake workspace can key one record per
    ``lake_id``.
    """

    variable: str
    source: str
    table_id: str
    data: pd.DataFrame | Path
    unit: str = ""
    crs: str | None = None
    source_unit: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def is_file_reference(self) -> bool:
        return isinstance(self.data, (str, Path))

    @property
    def frame(self) -> pd.DataFrame:
        """Return the table, reading Parquet from disk on first access."""
        if isinstance(self.data, (str, Path)):
            df = pd.read_parquet(str(self.data))
            self.data = df
            return df
        return self.data
