"""Runtime helpers shared by comparison launchers."""

from __future__ import annotations

from .config import materialize_simulation_config, write_toml_payload
from .mesh import (
    CellCentroidTable,
    resolve_bundle_cells,
    resolve_structured_shape_from_config,
    resolve_structured_shape_from_run_folder,
)
from .metadata import (
    _resolve_recorded_output_path,
    compact_run_metrics,
    discover_result_store,
    open_result_store_for_write,
    read_catalog_run_metadata,
    read_json_file,
    read_simulation_run_metadata,
    read_simulation_run_metrics,
)
from .observables import (
    PUBLIC_OBSERVABLE_CSV_FIELDNAMES,
    extract_observable_rows,
    normalize_observable_value,
    select_time_slices,
    write_observables_csv,
    write_public_observables_csv,
)
from .physics import is_nodata_value
from .series import (
    TimeSlice,
    VariableSeries,
    load_variable_series,
    mask_depth_series_from_head_nodata,
)

__all__ = (
    "CellCentroidTable",
    "TimeSlice",
    "VariableSeries",
    "_resolve_recorded_output_path",
    "PUBLIC_OBSERVABLE_CSV_FIELDNAMES",
    "compact_run_metrics",
    "discover_result_store",
    "extract_observable_rows",
    "is_nodata_value",
    "load_variable_series",
    "mask_depth_series_from_head_nodata",
    "materialize_simulation_config",
    "normalize_observable_value",
    "open_result_store_for_write",
    "read_catalog_run_metadata",
    "read_json_file",
    "read_simulation_run_metadata",
    "read_simulation_run_metrics",
    "resolve_bundle_cells",
    "resolve_structured_shape_from_config",
    "resolve_structured_shape_from_run_folder",
    "select_time_slices",
    "write_observables_csv",
    "write_public_observables_csv",
    "write_toml_payload",
)
