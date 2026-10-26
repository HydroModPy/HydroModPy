"""Readers of one sealed run: its source, its mesh, its series, its observables."""

from __future__ import annotations

from .mesh import CellCentroidTable, resolve_run_cells
from .observables import (
    PUBLIC_OBSERVABLE_CSV_FIELDNAMES,
    extract_observable_rows,
    normalize_observable_value,
    select_time_slices,
    write_observables_csv,
    write_public_observables_csv,
)
from .physics import is_nodata_value
from .run_source import RunNotComparableError, RunSource, open_run_source
from .series import (
    TimeSlice,
    VariableSeries,
    load_variable_series,
    mask_depth_series_from_head_nodata,
)

__all__ = (
    "PUBLIC_OBSERVABLE_CSV_FIELDNAMES",
    "CellCentroidTable",
    "RunNotComparableError",
    "RunSource",
    "TimeSlice",
    "VariableSeries",
    "extract_observable_rows",
    "is_nodata_value",
    "load_variable_series",
    "mask_depth_series_from_head_nodata",
    "normalize_observable_value",
    "open_run_source",
    "resolve_run_cells",
    "select_time_slices",
    "write_observables_csv",
    "write_public_observables_csv",
)
