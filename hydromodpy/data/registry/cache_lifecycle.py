"""Cache lifecycle: destructive ops and sidecar inserters.

Concern: every operation that mutates the catalog beyond ``register``
(invalidation, subsumption, prune, repair, cleanup) and the sidecar
table inserters (artifacts, provenance, stations, coverage, failures,
validation reports). Every SQL statement routes through
``catalog.backend`` (the cache-side ``CacheBackend`` port), never
through the raw ``_conn`` attribute.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger
from hydromodpy.data.registry.cache_store import json_or_none, try_unlink
from hydromodpy.data.registry.constants import SENTINEL_CUSTOM, SENTINEL_EMPTY

if TYPE_CHECKING:
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

logger = get_logger(__name__)


def invalidate(
    catalog: DataCatalogDuckDB,
    *,
    variable: str | None = None,
    source: str | None = None,
    station_id: str | None = None,
    delete_files: bool = False,
) -> int:
    """Remove matching entries. Returns count deleted.

    Sentinel entries (SENTINEL_CUSTOM, SENTINEL_EMPTY file_path) are
    excluded from deletion to preserve placeholder records.
    """
    try:
        clauses, params = _build_filter(variable, source, station_id)
        # Protect sentinel entries
        clauses.append("file_path NOT IN (?, ?)")
        params.extend([SENTINEL_CUSTOM, SENTINEL_EMPTY])
        where = " WHERE " + " AND ".join(clauses)

        backend = catalog.backend
        if delete_files:
            rows = backend.fetch_all(
                f"SELECT file_path FROM entries{where}",
                params,
            )
            for (fp,) in rows:
                try_unlink(fp)

        result = backend.fetch_all(
            f"DELETE FROM entries{where} RETURNING id",
            params,
        )
        return len(result)
    except Exception as exc:
        logger.warning("invalidate() failed: %s", exc)
        return 0


def subsume_entries(
    catalog: DataCatalogDuckDB,
    *,
    variable: str,
    source: str,
    bbox: tuple,
    date_start: str | None,
    date_end: str | None,
    exclude_id: int | None = None,
) -> int:
    """Delete grid entries fully contained within the given bbox+dates."""
    try:
        query = (
            "SELECT id, file_path FROM entries "
            "WHERE variable = ? AND source = ? "
            "AND station_id IS NULL AND is_custom = 0"
        )
        params: list = [variable, source]

        if exclude_id is not None:
            query += " AND id != ?"
            params.append(exclude_id)
        if bbox is not None:
            query += " AND bbox_xmin >= ? AND bbox_ymin >= ? AND bbox_xmax <= ? AND bbox_ymax <= ?"
            params.extend([bbox[0], bbox[1], bbox[2], bbox[3]])
        if date_start is not None:
            query += " AND date_start >= ?"
            params.append(date_start)
        if date_end is not None:
            query += " AND date_end <= ?"
            params.append(date_end)

        backend = catalog.backend
        rows = backend.fetch_all(query, params)
        count = 0
        for eid, fp in rows:
            try_unlink(fp)
            backend.execute("DELETE FROM entries WHERE id = ?", [eid])
            count += 1
        return count
    except Exception as exc:
        logger.warning("subsume_entries() failed: %s", exc)
        return 0


def write_artifact(
    catalog: DataCatalogDuckDB,
    *,
    artifact_type: str,
    path: str | Path,
    sha256: str | None = None,
    size_bytes: int | None = None,
    sim_id: str | None = None,
    variable: str | None = None,
) -> int:
    """Record an artifact row; returns its id."""
    backend = catalog.backend
    backend.execute(
        "INSERT INTO artifacts (sim_id, variable, artifact_type, path, sha256, size_bytes) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [sim_id, variable, artifact_type, str(path), sha256, size_bytes],
    )
    row = backend.fetch_one("SELECT currval('artifacts_seq')")
    return int(row[0]) if row else -1


def write_provenance(
    catalog: DataCatalogDuckDB,
    *,
    artifact_id: int | None = None,
    variable: str | None = None,
    source: str | None = None,
    input_hash: str | None = None,
    tool_name: str | None = None,
    tool_version: str | None = None,
    parameters: dict | None = None,
) -> int:
    """Record a provenance row; returns its id."""
    backend = catalog.backend
    backend.execute(
        "INSERT INTO provenance "
        "(artifact_id, variable, source, input_hash, tool_name, tool_version, parameters_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            artifact_id,
            variable,
            source,
            input_hash,
            tool_name,
            tool_version,
            json_or_none(parameters),
        ],
    )
    row = backend.fetch_one("SELECT currval('provenance_seq')")
    return int(row[0]) if row else -1


def upsert_station(
    catalog: DataCatalogDuckDB,
    *,
    station_id: str,
    variable: str,
    source: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    z: float | None = None,
    name: str | None = None,
    first_valid: str | None = None,
    last_valid: str | None = None,
) -> None:
    """Insert or update a station metadata row."""
    backend = catalog.backend
    existing = backend.fetch_one(
        "SELECT 1 FROM stations WHERE station_id = ? AND variable = ?",
        [station_id, variable],
    )
    if existing is None:
        backend.execute(
            "INSERT INTO stations "
            "(station_id, variable, source, lat, lon, z, name, first_valid, last_valid) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [station_id, variable, source, lat, lon, z, name, first_valid, last_valid],
        )
    else:
        backend.execute(
            "UPDATE stations SET source = ?, lat = ?, lon = ?, z = ?, "
            "name = ?, first_valid = ?, last_valid = ? "
            "WHERE station_id = ? AND variable = ?",
            [source, lat, lon, z, name, first_valid, last_valid, station_id, variable],
        )


def write_coverage(
    catalog: DataCatalogDuckDB,
    *,
    variable: str,
    source: str | None = None,
    region_wkt: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    n_stations: int | None = None,
) -> int:
    """Record a coverage row; returns its id."""
    backend = catalog.backend
    backend.execute(
        "INSERT INTO coverage "
        "(variable, source, region_wkt, period_start, period_end, n_stations) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [variable, source, region_wkt, period_start, period_end, n_stations],
    )
    row = backend.fetch_one("SELECT currval('coverage_seq')")
    return int(row[0]) if row else -1


def write_failure(
    catalog: DataCatalogDuckDB,
    *,
    variable: str | None = None,
    source_ref: str | None = None,
    error_type: str,
    message: str | None = None,
) -> int:
    """Record a failure row; returns its id."""
    backend = catalog.backend
    backend.execute(
        "INSERT INTO failures (variable, source_ref, error_type, message) VALUES (?, ?, ?, ?)",
        [variable, source_ref, error_type, message],
    )
    row = backend.fetch_one("SELECT currval('failures_seq')")
    return int(row[0]) if row else -1


def write_validation_report(
    catalog: DataCatalogDuckDB,
    *,
    schema_name: str,
    passed: bool,
    artifact_id: int | None = None,
    errors: list | dict | None = None,
) -> int:
    """Record a validation report; returns its id."""
    backend = catalog.backend
    backend.execute(
        "INSERT INTO validation_reports "
        "(artifact_id, schema_name, passed, errors_json) "
        "VALUES (?, ?, ?, ?)",
        [artifact_id, schema_name, bool(passed), json_or_none(errors)],
    )
    row = backend.fetch_one("SELECT currval('validation_reports_seq')")
    return int(row[0]) if row else -1


def prune_older_than(
    catalog: DataCatalogDuckDB,
    *,
    days: int,
    delete_files: bool = False,
) -> int:
    """Delete cache entries older than *days* days. Returns count removed."""
    backend = catalog.backend
    rows = backend.fetch_all(
        "SELECT id, file_path FROM entries WHERE created_at < now() - INTERVAL (?) DAY",
        [days],
    )
    count = 0
    for eid, fp in rows:
        if fp in (SENTINEL_CUSTOM, SENTINEL_EMPTY):
            continue
        if delete_files:
            try_unlink(fp)
        backend.execute("DELETE FROM entries WHERE id = ?", [eid])
        count += 1
    return count


def check_and_fix(catalog: DataCatalogDuckDB) -> dict[str, int]:
    """Scan entries and attempt to repair inconsistencies.

    - drop entries whose file is missing
    - refresh mtime for entries whose file changed
    Returns a summary dict ``{"dropped": N, "refreshed": N}``.
    """
    backend = catalog.backend
    summary = {"dropped": 0, "refreshed": 0}
    rows = backend.fetch_all("SELECT id, file_path, file_mtime FROM entries")
    for eid, fp, mtime in rows:
        if fp in (SENTINEL_CUSTOM, SENTINEL_EMPTY):
            continue
        p = Path(fp)
        if not p.exists():
            backend.execute("DELETE FROM entries WHERE id = ?", [eid])
            summary["dropped"] += 1
            continue
        try:
            current = p.stat().st_mtime
        except OSError:
            continue
        if mtime is None or abs(current - float(mtime)) > 1e-6:
            backend.execute(
                "UPDATE entries SET file_mtime = ? WHERE id = ?",
                [current, eid],
            )
            summary["refreshed"] += 1
    return summary


def cleanup(catalog: DataCatalogDuckDB) -> int:
    """Remove entries whose files no longer exist on disk."""
    backend = catalog.backend
    rows = backend.fetch_all("SELECT id, file_path FROM entries")
    ids_to_delete = []
    for eid, fp in rows:
        if fp in (SENTINEL_CUSTOM, SENTINEL_EMPTY):
            continue
        try:
            if not Path(fp).exists():
                ids_to_delete.append(eid)
        except OSError:
            ids_to_delete.append(eid)

    if ids_to_delete:
        placeholders = ",".join("?" * len(ids_to_delete))
        backend.execute(
            f"DELETE FROM entries WHERE id IN ({placeholders})",
            ids_to_delete,
        )
    return len(ids_to_delete)


def _build_filter(variable, source, station_id):
    clauses, params = [], []
    if variable:
        clauses.append("variable = ?")
        params.append(variable)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if station_id:
        clauses.append("station_id = ?")
        params.append(station_id)
    return clauses, params
