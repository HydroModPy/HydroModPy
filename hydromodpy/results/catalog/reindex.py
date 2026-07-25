"""Rebuild the project index from the run directories.

Why
---
``.hmp/index.duckdb`` is an index, not the truth. Every value it carries that
execution code reads back is also written inside the run directory it
describes (see :mod:`hydromodpy.results.manifest`), so losing the index must
cost nothing but the time to read the runs again. :func:`rebuild_index` is
that read-back, and it is the only way a run directory re-enters the index.

How
---
The rebuild never edits the live index. It fills a fresh database next to it
and publishes the result with one ``os.replace``: readers keep the old file
open until the swap and see the new one on their next statement. Running it
twice describes the project identically, because every row comes from a file
on disk. Only the database's own bookkeeping differs between two rebuilds:
the schema ledger (``_schema_version``, ``schema_migrations``) and the
``migrate`` audit row a fresh database writes when it applies the DDL.

What one run directory gives back
---------------------------------
=====================  ===========================================
Index table            Rebuilt from
=====================  ===========================================
simulations            ``tables.parquet/simulation.parquet``
parameters             ``tables.parquet/parameters.parquet``
metrics                ``tables.parquet/metrics.parquet``
provenance             ``tables.parquet/provenance.parquet``
geographic_features    ``tables.parquet/geographic_*.parquet``
geographic_metadata    ``manifest.json``, ``geometry.catchment``
runs_environment       ``provenance.json``
=====================  ===========================================

``timeseries``, ``budgets`` and ``mass_balance`` are not tables but views
over the Parquet payloads, so they come back with the files themselves.

The run **name is taken from the directory**, never from the files: a rename
moves the directory, so the tree is what the name is. The identity recorded
in ``manifest.json`` must match the snapshot, otherwise the directory is
reported and left out rather than indexed under a doubtful id.

What no run directory can give back (assumed loss)
--------------------------------------------------
- ``audit_log``: the history of what happened to a run.
- ``tags`` and ``sim_notes``: annotations, mutable after the seal.
- ``export_log``: which artefacts were published under ``share/``.
- ``tracked_files`` and ``observation_points``: recorded at run time only.
- trash state: a trashed run comes back as the completed run it was.
- ``calibration_sessions`` and ``calibration_iterations``: a session has no
  on-disk seal yet, so nothing under ``sessions/`` can be read back.

Two bookkeeping columns have no home on disk: ``runs_environment.recorded_at``
and ``provenance.valid_from``. They are dated by the seal time of their run
(``manifest.json``, ``sealed_at``) rather than by the wall clock, so a rebuild
stays reproducible instead of stamping itself into the data.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import (
    RUNS_DIRNAME,
    catalog_path_for,
    encode_workspace_path,
    runs_dir_for,
)
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.registration import split_stem_version
from hydromodpy.results.catalog.writes_helpers import (
    _python_value_type,
    geographic_feature_description,
)
from hydromodpy.results.manifest import read_manifest
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    RUN_MANIFEST_FILENAME,
    RUN_PROVENANCE_FILENAME,
    TABLES_DIRNAME,
)

if TYPE_CHECKING:
    from hydromodpy.results.catalog.ports import CatalogBackend

logger = get_logger(__name__)

GEOGRAPHIC_FEATURE_PREFIX = "geographic_"
"""Prefix of the per-feature GeoParquet payloads inside ``tables.parquet``."""

SIMULATION_SNAPSHOT_NAME = f"simulation{PARQUET_FILE_SUFFIX}"
"""One-row snapshot of the ``simulations`` row, written when a run completes."""

# Table column -> Parquet column, for the payloads whose file names a column
# differently from the index.
_METRICS_COLUMN_SOURCES: dict[str, str] = {"metric_name": "metric"}


@dataclass(frozen=True, slots=True)
class SkippedRun:
    """A run directory the rebuild left out, and why."""

    run: str
    reason: str


@dataclass(frozen=True, slots=True)
class ReindexReport:
    """Outcome of one index rebuild."""

    index_path: Path
    indexed: tuple[str, ...]
    skipped: tuple[SkippedRun, ...]
    rows: dict[str, int]


def rebuild_index(project_root: Path | str) -> ReindexReport:
    """Rebuild ``<project>/.hmp/index.duckdb`` from ``<project>/runs``.

    Fills a staging database, then publishes it atomically. The previous
    index stays readable for the whole rebuild and is replaced in one step.

    Parameters
    ----------
    project_root
        Project root holding ``runs/`` and ``.hmp/``.

    Returns
    -------
    ReindexReport
        Indexed run names, skipped directories with their reason, and the
        number of rows written per index table.
    """
    root = Path(project_root).expanduser().resolve()
    index_path = catalog_path_for(root)
    runs_dir = runs_dir_for(root)
    staging = index_path.with_name(f"{index_path.name}.rebuild-{uuid4().hex[:8]}")
    staging.parent.mkdir(parents=True, exist_ok=True)

    indexed: list[str] = []
    skipped: list[SkippedRun] = []
    rows: dict[str, int] = {}
    try:
        with Catalog(root, catalog_path=staging, runs_dir=runs_dir) as catalog:
            for run_dir in _run_directories(runs_dir):
                try:
                    counts = _index_run(catalog, run_dir)
                except Exception as exc:  # noqa: BLE001 - one bad run never aborts a rebuild
                    logger.warning("reindex left out %s: %s", run_dir.name, exc)
                    skipped.append(SkippedRun(run_dir.name, str(exc)))
                    continue
                indexed.append(run_dir.name)
                for table, count in counts.items():
                    rows[table] = rows.get(table, 0) + count
            catalog.connection.execute("CHECKPOINT")
        os.replace(staging, index_path)
        _forget_write_ahead_log(index_path)
    finally:
        _discard(staging)
    logger.info("reindexed %d run(s) into %s", len(indexed), index_path)
    return ReindexReport(
        index_path=index_path,
        indexed=tuple(indexed),
        skipped=tuple(skipped),
        rows=rows,
    )


# ---------------------------------------------------------------------------
# One run directory
# ---------------------------------------------------------------------------


def _index_run(catalog: Catalog, run_dir: Path) -> dict[str, int]:
    """Index one sealed run directory and return the rows written per table."""
    manifest = read_manifest(run_dir)
    tables_dir = run_dir / TABLES_DIRNAME
    snapshot = tables_dir / SIMULATION_SNAPSHOT_NAME
    if not snapshot.is_file():
        raise FileNotFoundError(
            f"No {SIMULATION_SNAPSHOT_NAME} under {tables_dir}: the run carries a manifest "
            "but not the index row it seals."
        )
    sim_id = _snapshot_sim_id(catalog.backend, snapshot)
    declared = str(manifest["run"]["sim_id"])
    if declared != sim_id:
        raise ValueError(
            f"{RUN_MANIFEST_FILENAME} names sim {declared[:8]} but the snapshot holds "
            f"{sim_id[:8]}: the run directory mixes two identities."
        )

    sealed_at = str(manifest["sealed_at"])
    counts = {"simulations": _insert_simulation(catalog.backend, run_dir, snapshot)}
    counts["parameters"] = _copy_payload(
        catalog.backend, "parameters", tables_dir / f"parameters{PARQUET_FILE_SUFFIX}"
    )
    counts["metrics"] = _copy_payload(
        catalog.backend,
        "metrics",
        tables_dir / f"metrics{PARQUET_FILE_SUFFIX}",
        sources=_METRICS_COLUMN_SOURCES,
    )
    counts["provenance"] = _copy_payload(
        catalog.backend,
        "provenance",
        tables_dir / f"provenance{PARQUET_FILE_SUFFIX}",
        overrides={"valid_from": _sql_text(sealed_at)},
    )
    counts["geographic_metadata"] = _insert_geographic_metadata(catalog.backend, sim_id, manifest)
    counts["geographic_features"] = _insert_geographic_features(catalog, sim_id, tables_dir)
    counts["runs_environment"] = _insert_environment(
        catalog.backend, sim_id, run_dir, recorded_at=sealed_at
    )
    return counts


def _insert_simulation(backend: CatalogBackend, run_dir: Path, snapshot: Path) -> int:
    """Insert the ``simulations`` row, naming the run after its directory."""
    dirname = run_dir.name
    stem, version = split_stem_version(dirname)
    overrides = {
        "name": _sql_text(dirname),
        "name_stem": _sql_text(stem),
        "version_int": str(version or 1),
        "storage_basename": _sql_text(dirname),
        "zarr_path": _sql_text(f"{RUNS_DIRNAME}/{dirname}/{FIELDS_STORE_NAME}"),
    }
    source = _sql_text(snapshot.as_posix())
    target_types = _column_types(backend, "simulations")
    available = set(_payload_columns(backend, source))
    columns = [name for name in target_types if name in available or name in overrides]
    column_sql = ", ".join(f'"{name}"' for name in columns)
    value_sql = ", ".join(
        overrides.get(name, f'CAST("{name}" AS {target_types[name]})') for name in columns
    )
    backend.execute(
        f"INSERT INTO simulations ({column_sql}) SELECT {value_sql} FROM read_parquet({source})"
    )
    return 1


def _copy_payload(
    backend: CatalogBackend,
    table: str,
    payload: Path,
    *,
    sources: dict[str, str] | None = None,
    overrides: dict[str, str] | None = None,
) -> int:
    """Copy a Parquet payload into ``table``, column by declared column.

    ``sources`` renames a table column onto the payload column that carries it;
    ``overrides`` gives an SQL literal for a column the payload does not carry
    and takes precedence over it. A run without that payload simply wrote no
    such row: it contributes zero.
    """
    if not payload.is_file():
        return 0
    source = _sql_text(payload.as_posix())
    target_types = _column_types(backend, table)
    available = set(_payload_columns(backend, source))
    mapping = sources or {}
    literals = overrides or {}
    selected = [
        name for name in target_types if name in literals or mapping.get(name, name) in available
    ]
    columns = ", ".join(f'"{name}"' for name in selected)
    values = ", ".join(
        literals.get(name, f'CAST("{mapping.get(name, name)}" AS {target_types[name]})')
        for name in selected
    )
    backend.execute(f"INSERT INTO {table} ({columns}) SELECT {values} FROM read_parquet({source})")
    row = backend.fetch_one(f"SELECT COUNT(*) FROM read_parquet({source})")
    return int(row[0]) if row else 0


def _insert_geographic_metadata(
    backend: CatalogBackend, sim_id: str, manifest: dict[str, Any]
) -> int:
    """Restore the catchment metadata the manifest carries.

    ``catch_area`` and the outlet live here: a discharge derived from runoff
    is scaled by the catchment area, so losing them yields a silently wrong
    series rather than an error.
    """
    catchment = manifest.get("geometry", {}).get("catchment") or {}
    for key, value in catchment.items():
        backend.execute(
            "INSERT INTO geographic_metadata (sim_id, key, value, value_type) VALUES (?, ?, ?, ?)",
            [sim_id, str(key), None if value is None else str(value), _python_value_type(value)],
        )
    return len(catchment)


def _insert_geographic_features(catalog: Catalog, sim_id: str, tables_dir: Path) -> int:
    """Describe every GeoParquet feature payload back into the index."""
    from hydromodpy.core.io.geoparquet import read_geoparquet

    payloads = sorted(tables_dir.glob(f"{GEOGRAPHIC_FEATURE_PREFIX}*{PARQUET_FILE_SUFFIX}"))
    for payload in payloads:
        feature_name = payload.name[len(GEOGRAPHIC_FEATURE_PREFIX) : -len(PARQUET_FILE_SUFFIX)]
        gdf = read_geoparquet(payload)
        geometry_kind, crs, properties = geographic_feature_description(gdf)
        catalog.backend.execute(
            "INSERT INTO geographic_features "
            "(sim_id, feature_name, geometry_kind, crs_wkt, geoparquet_path, properties) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                sim_id,
                feature_name,
                geometry_kind,
                crs,
                encode_workspace_path(catalog.workspace_path, payload),
                json.dumps(properties),
            ],
        )
    return len(payloads)


def _insert_environment(
    backend: CatalogBackend, sim_id: str, run_dir: Path, *, recorded_at: str
) -> int:
    """Restore ``runs_environment`` from the run provenance file."""
    path = run_dir / RUN_PROVENANCE_FILENAME
    if not path.is_file():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    git = payload.get("git", {})
    host = payload.get("platform", {})
    solver = payload.get("solver", {})
    environment = payload.get("environment", {})
    backend.execute(
        """INSERT INTO runs_environment
           (sim_id, python_version, hydromodpy_version, platform,
            hostname, user_name, cpu_info, memory_gb,
            git_commit, git_dirty, project_git_commit,
            solver_name, solver_binary_path,
            solver_binary_sha256, solver_version_text,
            conda_env_hash, env_packages, rng_seed, recorded_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            sim_id,
            payload.get("python", {}).get("version"),
            payload.get("tool", {}).get("version"),
            host.get("platform"),
            host.get("hostname"),
            host.get("user"),
            json.dumps(host.get("cpu") or {}),
            host.get("memory_gb"),
            git.get("commit"),
            git.get("dirty"),
            git.get("project_commit"),
            solver.get("name"),
            solver.get("binary_path"),
            solver.get("binary_sha256"),
            solver.get("version"),
            environment.get("conda_env_hash"),
            json.dumps(environment.get("packages_frozen") or []),
            environment.get("rng_seed"),
            recorded_at,
        ],
    )
    return 1


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _run_directories(runs_dir: Path) -> list[Path]:
    """Return the candidate run directories, dotfiles excluded."""
    if not runs_dir.is_dir():
        return []
    return sorted(p for p in runs_dir.iterdir() if p.is_dir() and not p.name.startswith("."))


def _snapshot_sim_id(backend: CatalogBackend, snapshot: Path) -> str:
    """Return the simulation id a one-row snapshot declares."""
    row = backend.fetch_one(
        f"SELECT CAST(sim_id AS VARCHAR) FROM read_parquet({_sql_text(snapshot.as_posix())})"
    )
    if row is None:
        raise ValueError(f"Empty snapshot at {snapshot}")
    return str(row[0])


def _column_types(backend: CatalogBackend, table: str) -> dict[str, str]:
    """Return ``{column: SQL type}`` for an index table, in declared order."""
    return {str(row[0]): str(row[1]) for row in backend.fetch_all(f"DESCRIBE {table}")}


def _payload_columns(backend: CatalogBackend, source: str) -> list[str]:
    """Return the column names a Parquet payload declares."""
    return [
        str(row[0]) for row in backend.fetch_all(f"DESCRIBE SELECT * FROM read_parquet({source})")
    ]


def _sql_text(value: str) -> str:
    """Return ``value`` as a single-quoted SQL literal."""
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _forget_write_ahead_log(index_path: Path) -> None:
    """Drop the write-ahead log of the index the rebuild just replaced.

    The published database is checkpointed and complete; a leftover ``.wal``
    belongs to the file that is gone and would be replayed onto the new one.
    """
    index_path.with_name(f"{index_path.name}.wal").unlink(missing_ok=True)


def _discard(staging: Path) -> None:
    """Remove a staging database that was never published."""
    staging.unlink(missing_ok=True)
    staging.with_name(f"{staging.name}.wal").unlink(missing_ok=True)


__all__ = [
    "ReindexReport",
    "SkippedRun",
    "rebuild_index",
]
