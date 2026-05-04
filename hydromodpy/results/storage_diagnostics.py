"""Diagnostics for the workspace result-storage layout.

The checks here are intentionally read-only. They are used by ``hmp doctor``
to report drift between the DuckDB catalog and per-simulation artefacts under
``simulations/`` without mutating old or locked workspaces.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from hydromodpy.results.storage_contract import (
    CATALOG_FILENAME,
    PARQUET_DIR_SUFFIX,
    PARQUET_FILE_SUFFIX,
    SIMULATIONS_DIRNAME,
    ZARR_SUFFIX,
    ZARR_ZIP_SUFFIX,
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
    basename: str
    storage_basename: str | None
    status: str | None
    zarr_path: str | None


def diagnose_result_storage(
    workspace: Path | str,
    *,
    catalog_path: Path | str | None = None,
    simulations_dir: Path | str | None = None,
) -> list[StorageDiagnostic]:
    """Return read-only diagnostics for one project result catalog.

    Parameters
    ----------
    workspace
        Project catalog root. By default the catalog is expected at
        ``<workspace>/hydromodpy.duckdb`` and artefacts below
        ``<workspace>/simulations``.
    catalog_path, simulations_dir
        Optional overrides for callers that resolved a TOML workspace config.
    """
    root = Path(workspace).expanduser().resolve()
    db = Path(catalog_path).expanduser().resolve() if catalog_path else root / CATALOG_FILENAME
    sims_dir = (
        Path(simulations_dir).expanduser().resolve()
        if simulations_dir
        else root / SIMULATIONS_DIRNAME
    )
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

    zarr_by_basename, parquet_by_basename = _scan_simulation_artefacts(sims_dir)
    tmp_files = _scan_tmp_parquet_files(sims_dir)
    registered = {row.basename for row in rows}

    missing_zarr = [
        row
        for row in rows
        if row.status == "completed"
        and not _row_zarr_exists(row, workspace=root, simulations_dir=sims_dir)
    ]
    if missing_zarr:
        first = missing_zarr[0]
        diagnostics.append(
            StorageDiagnostic(
                "results:missing_zarr",
                "WARN",
                f"{len(missing_zarr)} completed catalog row(s) without a Zarr artefact",
                f"first: {first.sim_id} ({first.basename})",
            )
        )

    orphan_zarr = sorted(set(zarr_by_basename) - registered)
    if orphan_zarr:
        paths = tuple(str(zarr_by_basename[basename]) for basename in orphan_zarr)
        diagnostics.append(
            StorageDiagnostic(
                "results:orphan_zarr",
                "WARN",
                f"{len(orphan_zarr)} Zarr artefact(s) without a catalog row",
                f"first: {orphan_zarr[0]}",
                paths,
            )
        )

    orphan_parquet = sorted(set(parquet_by_basename) - registered)
    if orphan_parquet:
        paths = tuple(str(parquet_by_basename[basename]) for basename in orphan_parquet)
        diagnostics.append(
            StorageDiagnostic(
                "results:orphan_parquet",
                "WARN",
                f"{len(orphan_parquet)} Parquet dir(s) without a catalog row",
                f"first: {orphan_parquet[0]}",
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
                (
                    f"{len(rows)} catalog row(s), "
                    f"{len(zarr_by_basename)} Zarr artefact(s), "
                    f"{len(parquet_by_basename)} Parquet dir(s)"
                ),
            )
        )
    return diagnostics


def storage_artefact_kind(path: Path) -> str | None:
    """Return the result artefact kind represented by ``path``."""
    name = path.name
    if name.endswith(ZARR_ZIP_SUFFIX) and path.is_file():
        return "zarr.zip"
    if name.endswith(ZARR_SUFFIX) and path.is_dir():
        return "zarr"
    if name.endswith(PARQUET_DIR_SUFFIX) and path.is_dir():
        return "parquet-dir"
    return None


def storage_artefact_basename(path: Path) -> str:
    """Return the storage basename for a Zarr or Parquet artefact path."""
    name = path.name
    for suffix in (ZARR_ZIP_SUFFIX, ZARR_SUFFIX, PARQUET_DIR_SUFFIX):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


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
    storage_expr = (
        "COALESCE(storage_basename, CAST(sim_id AS VARCHAR))"
        if "storage_basename" in columns
        else "CAST(sim_id AS VARCHAR)"
    )
    storage_raw_expr = "storage_basename" if "storage_basename" in columns else "NULL"
    status_expr = "status" if "status" in columns else "NULL"
    zarr_expr = "zarr_path" if "zarr_path" in columns else "NULL"
    rows = conn.execute(
        "SELECT CAST(sim_id AS VARCHAR) AS sim_id, "
        f"{storage_expr} AS storage_basename, "
        f"{storage_raw_expr} AS raw_storage_basename, "
        f"{status_expr} AS status, "
        f"{zarr_expr} AS zarr_path "
        "FROM simulations"
    ).fetchall()
    return [
        _SimulationRow(
            sim_id=str(sim_id),
            basename=str(basename),
            storage_basename=str(raw_basename) if raw_basename else None,
            status=str(status) if status is not None else None,
            zarr_path=str(zarr_path) if zarr_path else None,
        )
        for sim_id, basename, raw_basename, status, zarr_path in rows
    ]


def _scan_simulation_artefacts(sims_dir: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    zarr: dict[str, Path] = {}
    parquet: dict[str, Path] = {}
    if not sims_dir.is_dir():
        return zarr, parquet
    for path in sorted(sims_dir.iterdir()):
        kind = storage_artefact_kind(path)
        if kind is None:
            continue
        basename = storage_artefact_basename(path)
        if kind.startswith("zarr"):
            zarr[basename] = path
        elif kind == "parquet-dir":
            parquet[basename] = path
    return zarr, parquet


def _scan_tmp_parquet_files(sims_dir: Path) -> list[str]:
    if not sims_dir.is_dir():
        return []
    pattern = f"*{PARQUET_FILE_SUFFIX}.tmp"
    return [str(path) for path in sorted(sims_dir.rglob(pattern)) if path.is_file()]


def _row_zarr_exists(row: _SimulationRow, *, workspace: Path, simulations_dir: Path) -> bool:
    if row.zarr_path:
        path = Path(row.zarr_path)
        if not path.is_absolute():
            path = workspace / path
        if path.exists():
            return True
    return (
        simulations_dir.joinpath(f"{row.basename}{ZARR_SUFFIX}").exists()
        or simulations_dir.joinpath(f"{row.basename}{ZARR_ZIP_SUFFIX}").exists()
    )


__all__ = [
    "StorageDiagnostic",
    "diagnose_result_storage",
    "storage_artefact_basename",
    "storage_artefact_kind",
]
