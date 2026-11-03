"""The Parquet tables of one run, read from its directory.

A :class:`~hydromodpy.results.run.Run` reads its own rows (timeseries,
budgets, mass balance, parameters, declared points ...) from the files of
its run directory, ``tables.parquet/<name>.parquet``. The handle the run was
opened on, the project index or the store of a running run, only says where
that directory is. The index is never asked for a row a file holds, so a run
reads the same before and after its seal, and with no index at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import pandas as pd
import pyarrow as pa

from hydromodpy.results.manifest import PARAMETERS_TABLE_NAME
from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX
from hydromodpy.results.storage.parquet_io import read_checked_table
from hydromodpy.results.storage.parquet_schemas import PARAMETERS_SCHEMA, VIEW_SCHEMAS

if TYPE_CHECKING:
    from hydromodpy.results.run.view import Run

_SCHEMAS: dict[str, pa.Schema] = {**VIEW_SCHEMAS, PARAMETERS_TABLE_NAME: PARAMETERS_SCHEMA}


def read_run_table(
    run: Run,
    name: str,
    *,
    where: dict[str, Any] | None = None,
    columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Return the rows of table *name* of *run*, filtered on equality by *where*.

    A table the run never wrote reads as an empty frame with the declared
    columns, so a reader filters and selects without a special case.
    """
    tables = run._catalog.tables_dir_for(run.sim_id)  # noqa: SLF001 - same package
    path = tables / f"{name}{PARQUET_FILE_SUFFIX}"
    filters = [(key, "==", value) for key, value in (where or {}).items()] or None
    if not path.is_file():
        schema = _SCHEMAS.get(name)
        names = list(columns) if columns is not None else ([] if schema is None else schema.names)
        return pd.DataFrame(columns=names)
    return read_checked_table(path, columns=columns, filters=filters).to_pandas()


def has_rows(run: Run, name: str, **where: Any) -> bool:
    """Say whether table *name* of *run* holds a row matching *where*."""
    return not read_run_table(run, name, where=where).empty


__all__ = ["has_rows", "read_run_table"]
