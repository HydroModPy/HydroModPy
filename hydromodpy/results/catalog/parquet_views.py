"""Parquet-backed DuckDB view helpers for per-simulation tabular outputs.

The three views ``timeseries``, ``budgets`` and ``mass_balance`` map onto
``simulations/<basename>.parquet/<view>.parquet`` files. Empty typed
views are installed when no file exists yet, then swapped to a
``read_parquet`` view on the first write.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.results.catalog.constants import PARQUET_VIEW_NAMES
from hydromodpy.results.storage_contract import (
    PARQUET_DIR_SUFFIX,
    PARQUET_FILE_SUFFIX,
)

if TYPE_CHECKING:
    import duckdb


_PARQUET_VIEW_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "timeseries": (
        ("sim_id", "UUID"),
        ("station_id", "VARCHAR"),
        ("variable", "VARCHAR"),
        ("datetime", "TIMESTAMPTZ"),
        ("value", "DOUBLE"),
        ("unit", "VARCHAR"),
        ("qflag", "VARCHAR"),
    ),
    "budgets": (
        ("sim_id", "UUID"),
        ("timestep", "INTEGER"),
        ("zone_id", "VARCHAR"),
        ("component", "VARCHAR"),
        ("flux_in", "DOUBLE"),
        ("flux_out", "DOUBLE"),
        ("unit", "VARCHAR"),
    ),
    "mass_balance": (
        ("sim_id", "UUID"),
        ("timestep", "INTEGER"),
        ("total_in", "DOUBLE"),
        ("total_out", "DOUBLE"),
        ("storage_in", "DOUBLE"),
        ("storage_out", "DOUBLE"),
        ("percent_error", "DOUBLE"),
        ("unit", "VARCHAR"),
    ),
}


def parquet_view_columns(view_name: str) -> tuple[tuple[str, str], ...]:
    """Return ``((col, type), ...)`` for one of the three Parquet views."""
    try:
        return _PARQUET_VIEW_COLUMNS[view_name]
    except KeyError as exc:
        raise KeyError(f"Unknown Parquet view: {view_name!r}") from exc


def _empty_view_ddl(view_name: str) -> str:
    cols = _PARQUET_VIEW_COLUMNS[view_name]
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
    return any(simulations_dir.glob(f"*{PARQUET_DIR_SUFFIX}/{view_name}{PARQUET_FILE_SUFFIX}"))


def ensure_parquet_views(conn: duckdb.DuckDBPyConnection, simulations_dir: Path) -> None:
    """Create or refresh the three Parquet-backed views on ``conn``.

    If no Parquet file exists for a given view, an empty typed view is
    installed so ``SELECT * FROM <view>`` returns the right columns. On the
    next call after the first file lands, the view is swapped to
    ``read_parquet``.
    """
    simulations_dir = Path(simulations_dir)
    for view in PARQUET_VIEW_NAMES:
        if _parquet_files_exist(simulations_dir, view):
            ddl = _read_parquet_view_ddl(view, _glob_for_view(simulations_dir, view))
        else:
            ddl = _empty_view_ddl(view)
        conn.execute(ddl)


__all__ = [
    "ensure_parquet_views",
    "parquet_view_columns",
]
