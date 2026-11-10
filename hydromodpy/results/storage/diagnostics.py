"""Diagnostics for the project result-storage layout.

The checks here are intentionally read-only. They are used by ``hmp doctor``
to report drift between the index and the run directories under ``runs/``
without opening it for writing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from hydromodpy.core.state.layout import catalog_path_for, runs_dir_for
from hydromodpy.core.state.result_dirs import run_dir_rel
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    TABLES_DIRNAME,
)

DiagnosticStatus = Literal["OK", "WARN", "KO"]


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
    rel_dir: str
    status: str | None


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

    import duckdb

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
                    "index has no simulations table",
                    "Rebuild it with hmp catalog reindex.",
                )
            ]
        rows = _simulation_rows(conn)
    finally:
        conn.close()

    diagnostics: list[StorageDiagnostic] = []

    run_dirs = _scan_run_dirs(run_root)
    tmp_files = _scan_tmp_parquet_files(run_root)
    registered = {row.rel_dir for row in rows}

    missing_zarr = [
        row
        for row in rows
        if row.status == "completed" and not (root / row.rel_dir / FIELDS_STORE_NAME).exists()
    ]
    if missing_zarr:
        first = missing_zarr[0]
        diagnostics.append(
            StorageDiagnostic(
                "results:missing_zarr",
                "WARN",
                f"{len(missing_zarr)} completed index row(s) without a Zarr store",
                f"first: {first.sim_id} ({first.rel_dir})",
            )
        )

    orphan_runs = sorted(set(run_dirs) - registered)
    if orphan_runs:
        paths = tuple(str(run_dirs[rel_dir]) for rel_dir in orphan_runs)
        diagnostics.append(
            StorageDiagnostic(
                "results:orphan_runs",
                "WARN",
                f"{len(orphan_runs)} run director(y|ies) without an index row",
                f"first: {run_dirs[orphan_runs[0]].name}",
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

    changed = _runs_changed_since_seal(run_dirs.values())
    if changed:
        first_dir, first_problem = changed[0]
        diagnostics.append(
            StorageDiagnostic(
                "results:seal_digest",
                "WARN",
                f"{len(changed)} run(s) hold a file that no longer matches its seal",
                f"first: {first_dir.name}: {first_problem}",
                tuple(str(directory) for directory, _ in changed),
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


def _runs_changed_since_seal(directories) -> list[tuple[Path, str]]:
    """Return ``(run directory, first problem)`` for each sealed run whose digests differ."""
    from hydromodpy.results.record.manifest import is_sealed, seal_problems

    changed = []
    for directory in directories:
        if not is_sealed(directory):
            continue
        problems = seal_problems(directory)
        if problems:
            changed.append((directory, problems[0]))
    return changed


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


def _simulation_rows(conn) -> list[_SimulationRow]:
    rows = conn.execute(
        "SELECT CAST(s.sim_id AS VARCHAR), s.rel_dir, st.code "
        "FROM simulations s LEFT JOIN statuses st ON s.status_id = st.id"
    ).fetchall()
    return [
        _SimulationRow(
            sim_id=str(sim_id),
            rel_dir=str(rel_dir),
            status=str(status) if status is not None else None,
        )
        for sim_id, rel_dir, status in rows
    ]


def _scan_run_dirs(runs_dir: Path) -> dict[str, Path]:
    """Return the run directories under ``runs/``, keyed by their ``rel_dir``."""
    if not runs_dir.is_dir():
        return {}
    return {
        run_dir_rel(path.name): path
        for path in sorted(runs_dir.iterdir())
        if is_run_directory(path)
    }


def _scan_tmp_parquet_files(runs_dir: Path) -> list[str]:
    if not runs_dir.is_dir():
        return []
    pattern = f"*{PARQUET_FILE_SUFFIX}.tmp-*"
    return [str(path) for path in sorted(runs_dir.rglob(pattern)) if path.is_file()]


__all__ = [
    "StorageDiagnostic",
    "diagnose_result_storage",
    "is_run_directory",
]
