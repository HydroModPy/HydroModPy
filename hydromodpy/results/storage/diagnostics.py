"""Diagnostics for the project result-storage layout.

The checks here are intentionally read-only. They are used by ``hmp doctor``
to report drift between the DuckDB index and the run directories under
``runs/`` without mutating locked projects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from hydromodpy.core.state.paths import catalog_path_for, runs_dir_for
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    TABLES_DIRNAME,
)

DiagnosticStatus = Literal["OK", "WARN", "KO"]

LEGACY_PARQUET_TABLES = frozenset({"timeseries", "budgets", "mass_balance"})


@dataclass(frozen=True, slots=True)
class StorageDiagnostic:
    """One read-only storage diagnostic item."""

    name: str
    status: DiagnosticStatus
    detail: str
    hint: str | None = None
    paths: tuple[str, ...] = ()

    def to_check(self) -> dict[str, str | tuple[str, ...] | None]:
        """Return the dictionary shape expected by CLI reports."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _SimulationRow:
    sim_id: str
    dirname: str
    status: str | None
    zarr_path: str | None


def diagnose_result_storage(
    project_root: Path | str,
    *,
    catalog_path: Path | str | None = None,
    runs_dir: Path | str | None = None,
) -> list[StorageDiagnostic]:
    """Return read-only diagnostics for one project result index.

    Parameters
    ----------
    project_root
        Project root. By default the index is expected at
        ``<project>/.hmp/index.duckdb`` and the runs below ``<project>/runs``.
    catalog_path, runs_dir
        Optional overrides for callers that resolved a TOML workspace config.
    """
    root = Path(project_root).expanduser().resolve()
    db = Path(catalog_path).expanduser().resolve() if catalog_path else catalog_path_for(root)
    run_root = Path(runs_dir).expanduser().resolve() if runs_dir else runs_dir_for(root)
    if not db.is_file():
        return []

    try:
        import duckdb
    except ImportError:
        return [
            StorageDiagnostic(
                "results:catalog",
                "KO",
                "duckdb is not installed",
                "Install project dependencies before probing result storage.",
            )
        ]

    try:
        conn = duckdb.connect(str(db), read_only=True)
    except duckdb.IOException as exc:
        return [
            StorageDiagnostic(
                "results:catalog",
                "WARN",
                f"catalog busy: {exc}",
                "Close other HydroModPy sessions and retry.",
            )
        ]

    try:
        tables = _base_tables(conn)
        if "simulations" not in tables:
            return [
                StorageDiagnostic(
                    "results:catalog_schema",
                    "WARN",
                    "catalog has no simulations table",
                    "Open the workspace with a current HydroModPy version to migrate it.",
                )
            ]
        columns = _table_columns(conn, "simulations")
        rows = _simulation_rows(conn, columns)
    finally:
        conn.close()

    diagnostics: list[StorageDiagnostic] = []

    legacy = LEGACY_PARQUET_TABLES & tables
    if legacy:
        diagnostics.append(
            StorageDiagnostic(
                "results:legacy_tables",
                "WARN",
                f"legacy DuckDB result tables present: {', '.join(sorted(legacy))}",
                "Regenerate or migrate the workspace; tabular results now live in Parquet.",
            )
        )

    run_dirs = _scan_run_dirs(run_root)
    tmp_files = _scan_tmp_parquet_files(run_root)
    registered = {row.dirname for row in rows}

    missing_zarr = [
        row
        for row in rows
        if row.status == "completed" and not _row_zarr_exists(row, root=root, runs_dir=run_root)
    ]
    if missing_zarr:
        first = missing_zarr[0]
        diagnostics.append(
            StorageDiagnostic(
                "results:missing_zarr",
                "WARN",
                f"{len(missing_zarr)} completed index row(s) without a Zarr store",
                f"first: {first.sim_id} ({first.dirname})",
            )
        )

    orphan_runs = sorted(set(run_dirs) - registered)
    if orphan_runs:
        paths = tuple(str(run_dirs[dirname]) for dirname in orphan_runs)
        diagnostics.append(
            StorageDiagnostic(
                "results:orphan_runs",
                "WARN",
                f"{len(orphan_runs)} run director(y|ies) without an index row",
                f"first: {orphan_runs[0]}",
                paths,
            )
        )

    if tmp_files:
        diagnostics.append(
            StorageDiagnostic(
                "results:parquet_tmp",
                "WARN",
                f"{len(tmp_files)} temporary Parquet file(s) left on disk",
                f"first: {tmp_files[0]}",
                tuple(tmp_files),
            )
        )

    if not diagnostics:
        diagnostics.append(
            StorageDiagnostic(
                "results:layout",
                "OK",
                f"{len(rows)} index row(s), {len(run_dirs)} run director(y|ies)",
            )
        )
    return diagnostics


def is_run_directory(path: Path) -> bool:
    """Return True when ``path`` looks like a run directory."""
    if not path.is_dir():
        return False
    return (path / FIELDS_STORE_NAME).exists() or (path / TABLES_DIRNAME).is_dir()


def _base_tables(conn) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' AND table_type='BASE TABLE'"
        ).fetchall()
    }


def _table_columns(conn, table: str) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='main' AND table_name = ?",
            [table],
        ).fetchall()
    }


def _simulation_rows(conn, columns: set[str]) -> list[_SimulationRow]:
    storage_expr = "COALESCE(s.storage_basename, CAST(s.sim_id AS VARCHAR))"
    # v2 resolves the status code through the statuses dim table.
    if "status_id" in columns:
        status_expr = "st.code"
        status_join = "LEFT JOIN statuses st ON s.status_id = st.id"
    elif "status" in columns:
        status_expr = "s.status"
        status_join = ""
    else:
        status_expr = "NULL"
        status_join = ""
    zarr_expr = "s.zarr_path" if "zarr_path" in columns else "NULL"
    rows = conn.execute(
        "SELECT CAST(s.sim_id AS VARCHAR) AS sim_id, "
        f"{storage_expr} AS dirname, "
        f"{status_expr} AS status, "
        f"{zarr_expr} AS zarr_path "
        f"FROM simulations s {status_join}"
    ).fetchall()
    return [
        _SimulationRow(
            sim_id=str(sim_id),
            dirname=str(dirname),
            status=str(status) if status is not None else None,
            zarr_path=str(zarr_path) if zarr_path else None,
        )
        for sim_id, dirname, status, zarr_path in rows
    ]


def _scan_run_dirs(runs_dir: Path) -> dict[str, Path]:
    if not runs_dir.is_dir():
        return {}
    return {path.name: path for path in sorted(runs_dir.iterdir()) if is_run_directory(path)}


def _scan_tmp_parquet_files(runs_dir: Path) -> list[str]:
    if not runs_dir.is_dir():
        return []
    pattern = f"*{PARQUET_FILE_SUFFIX}.tmp-*"
    return [str(path) for path in sorted(runs_dir.rglob(pattern)) if path.is_file()]


def _row_zarr_exists(row: _SimulationRow, *, root: Path, runs_dir: Path) -> bool:
    if row.zarr_path:
        path = Path(row.zarr_path)
        if not path.is_absolute():
            path = root / path
        if path.exists():
            return True
    return (runs_dir / row.dirname / FIELDS_STORE_NAME).exists()


__all__ = [
    "StorageDiagnostic",
    "diagnose_result_storage",
    "is_run_directory",
]
