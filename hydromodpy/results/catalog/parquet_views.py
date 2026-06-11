"""Parquet-backed DuckDB view helpers for per-simulation tabular outputs.

Five views map onto ``simulations/<basename>.parquet/<view>.parquet`` files:
``timeseries``, ``budgets``, ``mass_balance``, ``metrics`` and ``provenance``.
Empty typed views are installed when no file exists yet, then swapped to a
``read_parquet`` view on the first write.

The column types are derived from the declared :mod:`hydromodpy.results
.parquet_schemas` so SQL views and Parquet payloads share one source of truth.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa

from hydromodpy.results.catalog.constants import PARQUET_VIEW_NAMES
from hydromodpy.results.parquet_schemas import VIEW_SCHEMAS
from hydromodpy.results.storage_contract import (
    PARQUET_DIR_SUFFIX,
    PARQUET_FILE_SUFFIX,
)

if TYPE_CHECKING:
    import duckdb


def _duckdb_type_for(arrow_type: pa.DataType) -> str:
    """Return the SQL type to declare for a pyarrow Arrow type."""
    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return "VARCHAR"
    if pa.types.is_int64(arrow_type):
        return "BIGINT"
    if pa.types.is_int32(arrow_type):
        return "INTEGER"
    if pa.types.is_float64(arrow_type):
        return "DOUBLE"
    if pa.types.is_float32(arrow_type):
        return "REAL"
    if pa.types.is_boolean(arrow_type):
        return "BOOLEAN"
    if pa.types.is_timestamp(arrow_type):
        return "TIMESTAMPTZ" if arrow_type.tz else "TIMESTAMP"
    if pa.types.is_binary(arrow_type) or pa.types.is_large_binary(arrow_type):
        return "BLOB"
    raise TypeError(f"Unsupported pyarrow type for DuckDB view: {arrow_type!r}")


def _columns_for(view_name: str) -> tuple[tuple[str, str], ...]:
    schema = VIEW_SCHEMAS[view_name]
    return tuple((field.name, _duckdb_type_for(field.type)) for field in schema)


def parquet_view_columns(view_name: str) -> tuple[tuple[str, str], ...]:
    """Return ``((col, type), ...)`` for one Parquet view, derived from pyarrow."""
    try:
        return _columns_for(view_name)
    except KeyError as exc:
        raise KeyError(f"Unknown Parquet view: {view_name!r}") from exc


def _empty_view_ddl(view_name: str) -> str:
    return _empty_view_ddl_named(view_name, view_name)


def _empty_view_ddl_named(schema_name: str, view_name: str) -> str:
    cols = _columns_for(schema_name)
    casts = ",\n    ".join(f"CAST(NULL AS {t}) AS {c}" for c, t in cols)
    return f"CREATE OR REPLACE VIEW {view_name} AS SELECT\n    {casts}\nWHERE 1=0"


def _read_parquet_view_ddl(view_name: str, glob_path: str) -> str:
    escaped = glob_path.replace("'", "''")
    return (
        f"CREATE OR REPLACE VIEW {view_name} AS "
        f"SELECT * FROM read_parquet('{escaped}', union_by_name=true)"
    )


def _glob_for_view(simulations_dir: Path, view_name: str) -> str:
    return str(simulations_dir / f"*{PARQUET_DIR_SUFFIX}" / f"{view_name}{PARQUET_FILE_SUFFIX}")


def _parquet_files_exist(simulations_dir: Path, view_name: str) -> bool:
    if not simulations_dir.is_dir():
        return False
    # ``*.parquet`` matches both container dirs and single-file payloads;
    # restrict the trailing segment with ``is_file()`` so an empty container
    # named like a view does not falsely report a payload.
    return any(
        p.is_file()
        for p in simulations_dir.glob(f"*{PARQUET_DIR_SUFFIX}/{view_name}{PARQUET_FILE_SUFFIX}")
    )


def _existing_tables(conn: duckdb.DuckDBPyConnection) -> set[str]:
    """Return the set of table names already declared on ``conn``."""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_type='BASE TABLE'"
    ).fetchall()
    return {str(r[0]) for r in rows}


def view_name_for(view: str, existing_tables: set[str]) -> str:
    """Pick a non-colliding DuckDB view name for a Parquet payload.

    ``metrics`` and ``provenance`` are already declared as DuckDB *tables* in
    the v2 schema. Creating a view with the same name would raise, so we
    transparently rename the per-sim Parquet view to ``<view>_parquet``. The
    main table remains the canonical SQL handle.
    """
    if view in existing_tables:
        return f"{view}_parquet"
    return view


def ensure_parquet_views(
    conn: duckdb.DuckDBPyConnection,
    simulations_dir: Path,
    *,
    temporary: bool = False,
) -> None:
    """Create or refresh every Parquet-backed view on ``conn``.

    If no Parquet file exists for a given view, an empty typed view is
    installed so ``SELECT * FROM <view>`` returns the right columns. On the
    next call after the first file lands, the view is swapped to
    ``read_parquet``.

    When a Parquet view collides with an existing DuckDB table (``metrics``,
    ``provenance``), a ``<view>_parquet`` alias is used instead so the SQL
    table remains intact. With ``temporary=True`` the views are session-local
    ``TEMPORARY`` views so a read-only connection can rebuild them.
    """
    simulations_dir = Path(simulations_dir)
    existing = _existing_tables(conn)
    for view in PARQUET_VIEW_NAMES:
        target_view = view_name_for(view, existing)
        if _parquet_files_exist(simulations_dir, view):
            ddl = _read_parquet_view_ddl(target_view, _glob_for_view(simulations_dir, view))
        else:
            ddl = _empty_view_ddl_named(view, target_view)
        if temporary:
            ddl = ddl.replace("CREATE OR REPLACE VIEW", "CREATE OR REPLACE TEMPORARY VIEW", 1)
        conn.execute(ddl)


__all__ = [
    "ensure_parquet_views",
    "parquet_view_columns",
    "view_name_for",
]
