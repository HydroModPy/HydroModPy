"""Data catalog backed by DuckDB."""

from __future__ import annotations

import time
from datetime import datetime
from hashlib import sha256
from pathlib import Path

import duckdb
import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import encode_workspace_path
from hydromodpy.data.registry.constants import SENTINEL_CUSTOM, SENTINEL_EMPTY
from hydromodpy.data.registry.migrations import ensure_schema as _ensure_cache_schema

logger = get_logger(__name__)

_RETRY = 8
_BACKOFF = 0.05


class _CatalogEntry:
    """Lightweight object mimicking the SQLAlchemy CatalogEntry for callers
    that access attributes by name (e.g. ``entry.station_id``)."""

    __slots__ = (
        "id",
        "variable",
        "source",
        "station_id",
        "bbox_xmin",
        "bbox_ymin",
        "bbox_xmax",
        "bbox_ymax",
        "crs",
        "date_start",
        "date_end",
        "frequency",
        "unit",
        "source_unit",
        "file_path",
        "file_mtime",
        "sha256",
        "created_at",
        "is_custom",
        "fetch_metadata",
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


class DataCatalogDuckDB:
    """DuckDB-backed data catalog."""

    def __init__(self, db_path: Path | str | None = None):
        self._db_path: Path | None = None
        if db_path is None:
            self._conn = duckdb.connect(":memory:")
        else:
            db_path = Path(db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db_path = db_path
            self._conn = duckdb.connect(str(db_path))

        _ensure_cache_schema(self._conn)

    @property
    def connection(self):
        """Underlying DuckDB connection (advanced usage)."""
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> DataCatalogDuckDB:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def _workspace_root(self) -> Path | None:
        """Return the workspace root inferred from the cache DB location."""
        if self._db_path is None:
            return None
        return self._db_path.parent.parent

    def _encode_path_for_storage(self, file_path: Path | str) -> str:
        """Encode ``file_path`` as a workspace-relative POSIX string.

        Falls back to ``str(file_path)`` for the in-memory catalog or when
        the target lies outside every supported anchor (workspace,
        ``cache://``, ``state://``). Anchored encoding is delegated to
        :func:`hydromodpy.core.state.paths.encode_workspace_path` and is
        attempted first when a workspace is known.
        """
        workspace = self._workspace_root()
        if workspace is None:
            return str(file_path)
        try:
            return encode_workspace_path(workspace, Path(file_path))
        except ValueError:
            # Path lies outside every portable anchor; keep the raw string
            # so the catalog still records something useful for ad-hoc
            # imports of custom files (tests, exploratory usage).
            return str(file_path)

    # -- register --------------------------------------------------------------

    def register(
        self,
        *,
        variable: str,
        source: str,
        file_path: str | Path,
        station_id: str | None = None,
        bbox: tuple | None = None,
        crs: str | None = None,
        date_start: datetime | str | None = None,
        date_end: datetime | str | None = None,
        frequency: str | None = None,
        unit: str | None = None,
        source_unit: str | None = None,
        is_custom: bool = False,
        file_mtime: float | None = None,
        file_sha256: str | None = None,
        fetch_metadata: dict | None = None,
    ) -> int:
        """Register or update a data file entry. Returns entry id (-1 on error)."""
        file_path = Path(file_path)
        resolved_path = self._resolve_entry_path(file_path, variable=variable)
        if file_mtime is None:
            try:
                mtime = resolved_path.stat().st_mtime if resolved_path.exists() else None
            except OSError:
                mtime = None
        else:
            mtime = file_mtime
        digest = file_sha256 or _sha256_or_none(resolved_path)
        self._reject_frozen_register(
            variable=variable,
            source=source,
            station_id=station_id,
            file_path=file_path,
            file_sha256=digest,
            is_custom=is_custom,
        )

        ds = _dt_to_str(date_start)
        de = _dt_to_str(date_end)
        bx = bbox or (None, None, None, None)
        # P3 workspace-relative encoding: anchor portable file_path on the
        # workspace root (or cache://, state://). Falls back to ``str(path)``
        # for in-memory catalogs (workspace unknown).
        encoded_path = self._encode_path_for_storage(file_path)

        # P9 provenance sidecar: write a JSON sidecar next to every catalog
        # input so downstream tools have the upstream metadata even without
        # the DuckDB catalog around. Best-effort: failures stay non-fatal.
        if digest is not None and resolved_path.is_file():
            _emit_input_sidecar(
                resolved_path,
                sha256=digest,
                source=source,
                crs=crs,
                bbox=bx,
            )

        # Look for existing entry
        if station_id is not None:
            existing = self._conn.execute(
                "SELECT id FROM entries WHERE variable = ? AND source = ? AND station_id = ?",
                [variable, source, station_id],
            ).fetchone()
        else:
            existing = self._conn.execute(
                "SELECT id FROM entries WHERE variable = ? AND source = ? "
                "AND station_id IS NULL AND file_path = ?",
                [variable, source, encoded_path],
            ).fetchone()

        for attempt in range(_RETRY):
            try:
                if existing is not None:
                    eid = existing[0]
                    self._conn.execute(
                        """UPDATE entries SET
                           bbox_xmin=?, bbox_ymin=?, bbox_xmax=?, bbox_ymax=?,
                           crs=?, date_start=?, date_end=?, frequency=?,
                           unit=?, source_unit=?, file_path=?, file_mtime=?, sha256=?,
                           is_custom=?, fetch_metadata=?
                           WHERE id=?""",
                        [
                            bx[0],
                            bx[1],
                            bx[2],
                            bx[3],
                            crs,
                            ds,
                            de,
                            frequency,
                            unit,
                            source_unit,
                            encoded_path,
                            mtime,
                            digest,
                            1 if is_custom else 0,
                            _json_or_none(fetch_metadata),
                            eid,
                        ],
                    )
                    return eid
                else:
                    self._conn.execute(
                        """INSERT INTO entries
                           (variable, source, station_id,
                            bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax,
                            crs, date_start, date_end, frequency,
                            unit, source_unit, file_path, file_mtime, sha256,
                            is_custom, fetch_metadata)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        [
                            variable,
                            source,
                            station_id,
                            bx[0],
                            bx[1],
                            bx[2],
                            bx[3],
                            crs,
                            ds,
                            de,
                            frequency,
                            unit,
                            source_unit,
                            encoded_path,
                            mtime,
                            digest,
                            1 if is_custom else 0,
                            _json_or_none(fetch_metadata),
                        ],
                    )
                    row = self._conn.execute("SELECT currval('entries_seq')").fetchone()
                    return row[0]
            except duckdb.IOException:
                if attempt < _RETRY - 1:
                    time.sleep(_BACKOFF * (2**attempt))
                else:
                    raise
            except Exception as exc:
                logger.warning("register() failed: %s", exc)
                return -1
        return -1

    # -- find_cached -----------------------------------------------------------

    def find_cached(
        self,
        *,
        variable: str,
        source: str,
        station_id: str | None = None,
        bbox: tuple | None = None,
        date_start: datetime | None = None,
        date_end: datetime | None = None,
    ) -> _CatalogEntry | None:
        """Find a cached entry covering the requested extent/period (superset)."""
        if bbox is not None and not (bbox[0] <= bbox[2] and bbox[1] <= bbox[3]):
            logger.warning("find_cached() called with inverted bbox: %s", bbox)
            return None

        query = "SELECT * FROM entries WHERE variable = ? AND source = ?"
        params: list = [variable, source]

        if station_id is not None:
            query += " AND station_id = ?"
            params.append(station_id)
        if bbox is not None:
            query += " AND bbox_xmin <= ? AND bbox_ymin <= ? AND bbox_xmax >= ? AND bbox_ymax >= ?"
            params.extend([bbox[0], bbox[1], bbox[2], bbox[3]])
        if date_start is not None:
            query += " AND date_start <= ?"
            params.append(_dt_to_str(date_start))
        if date_end is not None:
            query += " AND date_end >= ?"
            params.append(_dt_to_str(date_end))

        query += " ORDER BY id DESC LIMIT 1"
        row = self._conn.execute(query, params).fetchone()
        if row is None:
            self._reject_frozen_cache_miss(
                variable=variable,
                source=source,
                station_id=station_id,
            )
            return None

        cols = [d[0] for d in self._conn.description]
        entry = _CatalogEntry(**dict(zip(cols, row, strict=False)))
        self._reject_frozen_entry_mismatch(entry)
        return entry

    def _workspace_lockfile_path(self) -> Path | None:
        if self._db_path is None:
            return None
        from hydromodpy.data.data_freeze import LOCKFILE_NAME

        candidates = (
            self._db_path.parent.parent / LOCKFILE_NAME,
            self._db_path.parent / LOCKFILE_NAME,
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return candidates[0]

    def _resolve_entry_path(self, file_path: Path | str, *, variable: str | None = None) -> Path:
        path = Path(file_path)
        if path.is_absolute():
            return path
        candidates: list[Path] = []
        if self._db_path is not None:
            if variable:
                candidates.append(self._db_path.parent / variable / path)
            candidates.extend((self._db_path.parent / path, self._db_path.parent.parent / path))
        candidates.append(path)
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return candidates[0]

    @staticmethod
    def _frozen_enabled() -> bool:
        from hydromodpy.data.data_freeze import is_frozen_mode

        return is_frozen_mode()

    def _locked_artifacts(self):
        lockfile = self._workspace_lockfile_path()
        if lockfile is None or not lockfile.is_file():
            raise RuntimeError("Frozen data mode requires an existing hydromodpy.lock file.")
        from hydromodpy.data.data_freeze import read_lockfile

        return read_lockfile(lockfile)

    def _match_locked_artifact(
        self,
        *,
        variable: str,
        source: str,
        station_id: str | None,
        file_path: Path | str,
    ):
        path = Path(file_path)
        resolved = self._resolve_entry_path(path, variable=variable)
        artifacts = self._locked_artifacts()
        for artifact in artifacts:
            if (
                artifact.variable == variable
                and artifact.source == source
                and artifact.station_id == station_id
                and (
                    Path(artifact.file_path) == path
                    or Path(artifact.file_path) == resolved
                    or self._resolve_entry_path(artifact.file_path, variable=variable) == resolved
                )
            ):
                return artifact
        return None

    def _reject_frozen_cache_miss(
        self,
        *,
        variable: str,
        source: str,
        station_id: str | None,
    ) -> None:
        if not self._frozen_enabled():
            return
        self._locked_artifacts()
        raise RuntimeError(
            "Frozen data mode forbids cache misses: "
            f"{variable}/{source}/{station_id or '-'} is absent from the local catalog."
        )

    def _reject_frozen_entry_mismatch(self, entry: _CatalogEntry) -> None:
        if not self._frozen_enabled():
            return
        artifact = self._match_locked_artifact(
            variable=entry.variable,
            source=entry.source,
            station_id=entry.station_id,
            file_path=entry.file_path,
        )
        if artifact is None:
            raise RuntimeError(
                "Frozen data mode forbids catalog entries absent from hydromodpy.lock: "
                f"{entry.variable}/{entry.source}/{entry.station_id or '-'}."
            )
        observed = entry.sha256 or _sha256_or_none(
            self._resolve_entry_path(entry.file_path, variable=entry.variable)
        )
        if observed != artifact.sha256:
            raise RuntimeError(
                "Frozen data mode detected a SHA-256 mismatch for "
                f"{entry.variable}/{entry.source}/{entry.station_id or '-'}."
            )

    def _reject_frozen_register(
        self,
        *,
        variable: str,
        source: str,
        station_id: str | None,
        file_path: Path,
        file_sha256: str | None,
        is_custom: bool,
    ) -> None:
        if not self._frozen_enabled():
            return
        artifact = self._match_locked_artifact(
            variable=variable,
            source=source,
            station_id=station_id,
            file_path=file_path,
        )
        if artifact is None:
            kind = "custom file" if is_custom else "downloaded artefact"
            raise RuntimeError(
                f"Frozen data mode forbids registering a {kind} absent from hydromodpy.lock: "
                f"{variable}/{source}/{station_id or '-'}."
            )
        if file_sha256 != artifact.sha256:
            raise RuntimeError(
                "Frozen data mode forbids registering an artefact whose SHA-256 does not match "
                f"hydromodpy.lock: {variable}/{source}/{station_id or '-'}."
            )

    # -- list_entries ----------------------------------------------------------

    def list_entries(
        self,
        *,
        variable: str | None = None,
        source: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> pd.DataFrame:
        """List catalog entries as a DataFrame."""
        query = (
            "SELECT id, variable, source, station_id, date_start, date_end, "
            "file_path, file_mtime, sha256, source_unit, is_custom, fetch_metadata FROM entries"
        )
        params: list = []
        clauses = []
        if variable:
            clauses.append("variable = ?")
            params.append(variable)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += f" OFFSET {offset}"
        if limit is not None:
            query += f" LIMIT {limit}"

        df = self._conn.execute(query, params).fetchdf()
        if "is_custom" in df.columns:
            df["is_custom"] = df["is_custom"].astype(bool)
        for column in ("date_start", "date_end"):
            if column in df.columns:
                df[column] = df[column].map(_format_catalog_timestamp)
        return df

    # -- invalidate ------------------------------------------------------------

    def invalidate(
        self,
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

            if delete_files:
                rows = self._conn.execute(
                    f"SELECT file_path FROM entries{where}",
                    params,
                ).fetchall()
                for (fp,) in rows:
                    _try_unlink(fp)

            result = self._conn.execute(
                f"DELETE FROM entries{where} RETURNING id",
                params,
            ).fetchall()
            return len(result)
        except Exception as exc:
            logger.warning("invalidate() failed: %s", exc)
            return 0

    # -- subsume_entries -------------------------------------------------------

    def subsume_entries(
        self,
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
                query += (
                    " AND bbox_xmin >= ? AND bbox_ymin >= ? AND bbox_xmax <= ? AND bbox_ymax <= ?"
                )
                params.extend([bbox[0], bbox[1], bbox[2], bbox[3]])
            if date_start is not None:
                query += " AND date_start >= ?"
                params.append(date_start)
            if date_end is not None:
                query += " AND date_end <= ?"
                params.append(date_end)

            rows = self._conn.execute(query, params).fetchall()
            count = 0
            for eid, fp in rows:
                _try_unlink(fp)
                self._conn.execute("DELETE FROM entries WHERE id = ?", [eid])
                count += 1
            return count
        except Exception as exc:
            logger.warning("subsume_entries() failed: %s", exc)
            return 0

    # -- artifacts -------------------------------------------------------------

    def write_artifact(
        self,
        *,
        artifact_type: str,
        path: str | Path,
        sha256: str | None = None,
        size_bytes: int | None = None,
        sim_id: str | None = None,
        variable: str | None = None,
    ) -> int:
        """Record an artifact row; returns its id."""
        self._conn.execute(
            "INSERT INTO artifacts (sim_id, variable, artifact_type, path, sha256, size_bytes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [sim_id, variable, artifact_type, str(path), sha256, size_bytes],
        )
        row = self._conn.execute("SELECT currval('artifacts_seq')").fetchone()
        return int(row[0]) if row else -1

    # -- provenance ------------------------------------------------------------

    def write_provenance(
        self,
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
        self._conn.execute(
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
                _json_or_none(parameters),
            ],
        )
        row = self._conn.execute("SELECT currval('provenance_seq')").fetchone()
        return int(row[0]) if row else -1

    # -- stations --------------------------------------------------------------

    def upsert_station(
        self,
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
        existing = self._conn.execute(
            "SELECT 1 FROM stations WHERE station_id = ? AND variable = ?",
            [station_id, variable],
        ).fetchone()
        if existing is None:
            self._conn.execute(
                "INSERT INTO stations "
                "(station_id, variable, source, lat, lon, z, name, first_valid, last_valid) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [station_id, variable, source, lat, lon, z, name, first_valid, last_valid],
            )
        else:
            self._conn.execute(
                "UPDATE stations SET source = ?, lat = ?, lon = ?, z = ?, "
                "name = ?, first_valid = ?, last_valid = ? "
                "WHERE station_id = ? AND variable = ?",
                [source, lat, lon, z, name, first_valid, last_valid, station_id, variable],
            )

    # -- coverage --------------------------------------------------------------

    def write_coverage(
        self,
        *,
        variable: str,
        source: str | None = None,
        region_wkt: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        n_stations: int | None = None,
    ) -> int:
        """Record a coverage row; returns its id."""
        self._conn.execute(
            "INSERT INTO coverage "
            "(variable, source, region_wkt, period_start, period_end, n_stations) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [variable, source, region_wkt, period_start, period_end, n_stations],
        )
        row = self._conn.execute("SELECT currval('coverage_seq')").fetchone()
        return int(row[0]) if row else -1

    # -- failures --------------------------------------------------------------

    def write_failure(
        self,
        *,
        variable: str | None = None,
        source_ref: str | None = None,
        error_type: str,
        message: str | None = None,
    ) -> int:
        """Record a failure row; returns its id."""
        self._conn.execute(
            "INSERT INTO failures (variable, source_ref, error_type, message) VALUES (?, ?, ?, ?)",
            [variable, source_ref, error_type, message],
        )
        row = self._conn.execute("SELECT currval('failures_seq')").fetchone()
        return int(row[0]) if row else -1

    # -- validation_reports ----------------------------------------------------

    def write_validation_report(
        self,
        *,
        schema_name: str,
        passed: bool,
        artifact_id: int | None = None,
        errors: list | dict | None = None,
    ) -> int:
        """Record a validation report; returns its id."""
        self._conn.execute(
            "INSERT INTO validation_reports "
            "(artifact_id, schema_name, passed, errors_json) "
            "VALUES (?, ?, ?, ?)",
            [artifact_id, schema_name, bool(passed), _json_or_none(errors)],
        )
        row = self._conn.execute("SELECT currval('validation_reports_seq')").fetchone()
        return int(row[0]) if row else -1

    # -- introspection ---------------------------------------------------------

    def table_names(self) -> list[str]:
        """Return the list of tables present in the catalog."""
        rows = self._conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        ).fetchall()
        return [r[0] for r in rows]

    def prune_older_than(
        self,
        *,
        days: int,
        delete_files: bool = False,
    ) -> int:
        """Delete cache entries older than *days* days. Returns count removed."""
        rows = self._conn.execute(
            "SELECT id, file_path FROM entries WHERE created_at < now() - INTERVAL (?) DAY",
            [days],
        ).fetchall()
        count = 0
        for eid, fp in rows:
            if fp in (SENTINEL_CUSTOM, SENTINEL_EMPTY):
                continue
            if delete_files:
                _try_unlink(fp)
            self._conn.execute("DELETE FROM entries WHERE id = ?", [eid])
            count += 1
        return count

    def check_and_fix(self) -> dict[str, int]:
        """Scan entries and attempt to repair inconsistencies.

        - drop entries whose file is missing
        - refresh mtime for entries whose file changed
        Returns a summary dict ``{"dropped": N, "refreshed": N}``.
        """
        summary = {"dropped": 0, "refreshed": 0}
        rows = self._conn.execute("SELECT id, file_path, file_mtime FROM entries").fetchall()
        for eid, fp, mtime in rows:
            if fp in (SENTINEL_CUSTOM, SENTINEL_EMPTY):
                continue
            p = Path(fp)
            if not p.exists():
                self._conn.execute("DELETE FROM entries WHERE id = ?", [eid])
                summary["dropped"] += 1
                continue
            try:
                current = p.stat().st_mtime
            except OSError:
                continue
            if mtime is None or abs(current - float(mtime)) > 1e-6:
                self._conn.execute(
                    "UPDATE entries SET file_mtime = ? WHERE id = ?",
                    [current, eid],
                )
                summary["refreshed"] += 1
        return summary

    # -- cleanup ---------------------------------------------------------------

    def cleanup(self) -> int:
        """Remove entries whose files no longer exist on disk."""
        rows = self._conn.execute("SELECT id, file_path FROM entries").fetchall()
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
            self._conn.execute(
                f"DELETE FROM entries WHERE id IN ({placeholders})",
                ids_to_delete,
            )
        return len(ids_to_delete)


def _dt_to_str(dt: datetime | str | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def _format_catalog_timestamp(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    ts = pd.Timestamp(value)
    if ts.tz is not None:
        ts = ts.tz_localize(None)
    return ts.isoformat(timespec="seconds")


def _json_or_none(d: dict | None) -> str | None:
    if d is None:
        return None
    import json

    return json.dumps(d)


def _sha256_or_none(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _emit_input_sidecar(
    path: Path,
    *,
    sha256: str,
    source: str,
    crs: str | None,
    bbox: tuple,
) -> None:
    """Write the P3 JSON sidecar next to a freshly registered raw input.

    Best-effort: any failure is logged at debug level and never propagates,
    so a sidecar issue cannot block the catalog registration.
    """
    try:
        from hydromodpy.data.sidecars import Sidecar, resolve_fetched_at, write_sidecar

        bbox_payload: tuple[float, float, float, float] | None = None
        if all(value is not None for value in bbox):
            bbox_payload = tuple(float(v) for v in bbox)  # type: ignore[assignment]
        sidecar = Sidecar(
            source=str(source),
            fetched_at=resolve_fetched_at(str(source)),
            sha256=str(sha256),
            crs=str(crs) if crs else None,
            bbox=bbox_payload,
        )
        write_sidecar(path, sidecar)
    except Exception as exc:  # pragma: no cover - non-fatal
        logger.debug("Sidecar write failed for %s: %s", path, exc)


def _try_unlink(fp: str) -> None:
    if fp in (SENTINEL_CUSTOM, SENTINEL_EMPTY):
        return
    try:
        p = Path(fp)
        if p.exists():
            p.unlink()
    except OSError as exc:
        logger.warning("Failed to delete file %s: %s", fp, exc)
