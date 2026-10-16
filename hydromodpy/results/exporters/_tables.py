"""Read the Parquet tables of one run from its directory, never from the index.

The store of a run being computed and the catalog of a project both name the
tables directory of a run (``tables_dir_for``). An exporter reads a table
there, so an export written during the run and one written later from the
catalog read the same file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq

from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX

TIMESERIES_TABLE = "timeseries"
"""The table the series of a run are stored in."""

BUDGETS_TABLE = "budgets"
"""The table the water budget of a run is stored in."""

FACE_FAMILIES_TABLE = "mesh_face_families"
"""The table of the mesh faces that lie on a line family."""


def table_path(store: Any, sim_id: str, table: str) -> Path:
    """Return the Parquet file of one table of a run."""
    return Path(store.tables_dir_for(sim_id)) / f"{table}{PARQUET_FILE_SUFFIX}"


def table_rows(store: Any, sim_id: str, table: str) -> int:
    """Return the number of rows of one table of a run, 0 when the run stored none."""
    path = table_path(store, sim_id, table)
    if not path.is_file():
        return 0
    return int(pq.ParquetFile(path).metadata.num_rows)


def distinct_values(store: Any, sim_id: str, table: str, column: str) -> list[str]:
    """Return the distinct values of one column of a table of a run, in sorted order."""
    path = table_path(store, sim_id, table)
    if not path.is_file():
        return []
    values = pc.unique(pq.read_table(path, columns=[column]).column(column))
    return sorted(str(value) for value in values.to_pylist() if value is not None)


def geographic_features(store: Any, sim_id: str) -> list[str]:
    """Return the vector layers a run stored, read from the files of its tables directory."""
    from hydromodpy.results.storage.run_store import GEOGRAPHIC_FEATURE_PREFIX

    tables = Path(store.tables_dir_for(sim_id))
    if not tables.is_dir():
        return []
    prefix, suffix = GEOGRAPHIC_FEATURE_PREFIX, PARQUET_FILE_SUFFIX
    return sorted(
        path.name[len(prefix) : -len(suffix)] for path in tables.glob(f"{prefix}*{suffix}")
    )


def read_table(store: Any, sim_id: str, table: str) -> pd.DataFrame:
    """Return one table of a run without its ``sim_id`` column, empty when the run stored none."""
    path = table_path(store, sim_id, table)
    if not path.is_file():
        return pd.DataFrame()
    frame = pd.read_parquet(path)
    return frame.drop(columns="sim_id", errors="ignore").reset_index(drop=True)
