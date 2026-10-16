"""Build and refresh ``.hmp/index.duckdb`` from the project tree.

Why
---
The index is derived: every value it holds is read from a file of ``runs/``
or ``sessions/``, so losing it costs the time of reading them again. No run
and no calibration ever writes it. The launcher calls :func:`index_new_runs`
after a worker exits, ``hmp catalog reindex`` calls :func:`rebuild_index`,
and both write a staging database that is published in one rename: a reader
holding the previous file keeps reading it, the next opener gets the new one.

The incremental refresh is a diff
---------------------------------
Each result directory is keyed by its relative directory and by what it
carries: ``manifest.json`` names a ``sim_id``, ``outcome.json`` an
``attempt_id``, ``session.json`` a ``session_id``. The stamp of a directory is
the newest mtime of those files, of ``annotations.json`` and of the trial
journal. A directory that is new, or whose key or stamp changed, is read
again; one that disappeared loses its rows; the others are left as they are.
A renamed directory is a removal and an insertion under the new name, with
the same ``sim_id``: the links by id do not move. A retry writes a new
``attempt_id``: the previous attempt stays in ``attempts``, the case row
follows the new one.

What one directory gives back
-----------------------------
=======================  =======================================================
Index table              Rebuilt from
=======================  =======================================================
cases, attempts          ``outcome.json``, ``attempts/<n>/outcome.json``,
                         ``logs/heartbeat.json``, the presence of the seal
simulations              ``tables.parquet/simulation.parquet`` and ``manifest.json``;
                         ``config.toml`` for the frozen configuration
parameters, metrics      ``manifest.json`` (``parameters``, ``metrics``)
tracked_files            ``manifest.json`` (``inputs``)
geographic_metadata      ``manifest.json`` (``geometry.catchment``)
geographic_features      ``tables.parquet/geographic_*.parquet``
provenance               ``tables.parquet/provenance.parquet``
runs_environment         ``provenance.json``
tags, sim_notes          ``annotations.json``
calibration_sessions     ``sessions/<name>/session.json``
calibration_phases       ``sessions/<name>/phases/<phase>/session.json``
calibration_iterations   ``sessions/<name>/trials.jsonl``
sites                    the ``site`` blocks of the seals, counted over cases
=======================  =======================================================

The label of a sealed run is computed here, with the rules and the known
issues of this build, and dated. The rule version and a digest of the known
issues register are stamped in ``index_meta`` next to the schema version: an
index labelled by another build is rebuilt whole at the next pass, so a new
rule or a new known issue reclassifies every run without touching its files.
The run name is taken from the directory, never from the files: a rename
moves the directory, so the tree is what the name is.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import duckdb
import pyarrow.parquet as pq

from hydromodpy.core.io.atomic_replace import rename_over_open_file
from hydromodpy.core.io.db_retry import connect_with_retry
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import (
    TRIALS_DIRNAME,
    catalog_path_for,
    encode_workspace_path,
    run_dir_rel,
    runs_dir_for,
    session_dir_rel,
    sessions_dir_for,
    trial_dir_rel,
)
from hydromodpy.core.version import __version__
from hydromodpy.results.annotations import read_annotations
from hydromodpy.results.catalog.index_schema import (
    INDEX_META_TABLE,
    INDEX_SCHEMA_VERSION,
    META_INDEXED_AT,
    META_KNOWN_ISSUES_DIGEST,
    META_RULE_VERSION,
    SESSION_CHILD_TABLES,
    SIMULATION_CHILD_TABLES,
    create_index_schema,
    read_index_schema_version,
)
from hydromodpy.results.catalog.registration import split_stem_version
from hydromodpy.results.catalog.views import ensure_views
from hydromodpy.results.export.run_identity import label_of
from hydromodpy.results.heartbeat import read_heartbeat
from hydromodpy.results.manifest import Manifest, read_manifest
from hydromodpy.results.outcome import Outcome, effective_status, read_outcome
from hydromodpy.results.record import RunProvenance
from hydromodpy.results.session.descriptor import SessionDescriptor, read_session
from hydromodpy.results.session.journal import read_trials
from hydromodpy.results.session.phase import list_phases
from hydromodpy.results.storage.contract import (
    PARQUET_FILE_SUFFIX,
    RUN_ANNOTATIONS_FILENAME,
    RUN_ATTEMPTS_DIRNAME,
    RUN_CONFIG_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_OUTCOME_FILENAME,
    RUN_PROVENANCE_FILENAME,
    SESSION_DESCRIPTOR_FILENAME,
    SESSION_PHASES_DIRNAME,
    SESSION_TRIALS_FILENAME,
    SIMULATION_TABLE_NAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.json_io import read_json
from hydromodpy.results.validity_rules import RULE_VERSION, load_known_issues

logger = get_logger(__name__)

GEOGRAPHIC_FEATURE_PREFIX = "geographic_"
"""Prefix of the per-feature GeoParquet payloads inside ``tables.parquet``."""

EntryKind = Literal["run", "trial", "session"]


@dataclass(frozen=True, slots=True)
class DiskEntry:
    """One result directory as the scan sees it: where it is and what stamps it."""

    rel_dir: str
    kind: EntryKind
    path: Path
    key: str
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class SkippedEntry:
    """A directory the indexer left out, and why."""

    rel_dir: str
    reason: str


@dataclass(frozen=True, slots=True)
class IndexReport:
    """What one indexing pass did."""

    index_path: Path
    full: bool
    indexed: tuple[str, ...]
    sessions: tuple[str, ...]
    removed: tuple[str, ...]
    skipped: tuple[SkippedEntry, ...]
    rows: dict[str, int]

    @property
    def unchanged(self) -> bool:
        """True when the pass found nothing to write."""
        return not self.indexed and not self.sessions and not self.removed and not self.skipped


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def rebuild_index(project_root: Path | str) -> IndexReport:
    """Rebuild the whole index from ``runs/`` and ``sessions/`` and publish it."""
    root = Path(project_root).expanduser().resolve()
    return _write_index(root, scan_tree(root), incremental=False)


def index_new_runs(project_root: Path | str, *, incremental: bool = True) -> IndexReport:
    """Bring the index up to date with the tree, by a diff when it can.

    Without an index, with an index of another schema version, with an index
    labelled by other rules or another known issues register, or with
    ``incremental=False``, the index is rebuilt whole. Otherwise only the
    directories that appeared, changed or disappeared since the last pass are
    written, and a tree that did not move writes nothing.
    """
    root = Path(project_root).expanduser().resolve()
    disk = scan_tree(root)
    index_path = catalog_path_for(root)
    if not incremental or not _index_is_of_this_build(index_path):
        return _write_index(root, disk, incremental=False)
    current = _read_indexed(index_path)
    changed = {
        rel_dir
        for rel_dir, entry in disk.items()
        if current.get(rel_dir) != (entry.key, entry.mtime_ns)
    }
    removed = set(current) - set(disk)
    if not changed and not removed:
        return IndexReport(index_path, False, (), (), (), (), {})
    return _write_index(root, disk, incremental=True, changed=changed, removed=removed)


def index_is_current(project_root: Path | str) -> bool:
    """Return whether the index describes the tree as it stands."""
    root = Path(project_root).expanduser().resolve()
    index_path = catalog_path_for(root)
    if not _index_is_of_this_build(index_path):
        return False
    disk = scan_tree(root)
    current = _read_indexed(index_path)
    return {rel: (e.key, e.mtime_ns) for rel, e in disk.items()} == current


# ---------------------------------------------------------------------------
# Scanning the tree
# ---------------------------------------------------------------------------


def scan_tree(project_root: Path) -> dict[str, DiskEntry]:
    """Return every result directory of the project, keyed by its relative directory.

    A directory under ``runs/`` or ``sessions/`` that carries neither an
    outcome, a manifest nor a session descriptor is not a result and is left
    out. A trial is a numbered directory under ``sessions/<name>/trials/``.
    """
    entries: dict[str, DiskEntry] = {}
    runs_dir = runs_dir_for(project_root)
    if runs_dir.is_dir():
        for path in sorted(runs_dir.iterdir()):
            if not path.is_dir() or path.name.startswith("."):
                continue
            entry = _run_entry(run_dir_rel(path.name), "run", path)
            if entry is not None:
                entries[entry.rel_dir] = entry
    sessions_dir = sessions_dir_for(project_root)
    if sessions_dir.is_dir():
        for path in sorted(sessions_dir.iterdir()):
            if not path.is_dir() or path.name.startswith("."):
                continue
            entry = _session_entry(session_dir_rel(path.name), path)
            if entry is not None:
                entries[entry.rel_dir] = entry
            trials = path / TRIALS_DIRNAME
            if not trials.is_dir():
                continue
            for trial_path in sorted(trials.iterdir()):
                if not trial_path.is_dir() or not trial_path.name.isdigit():
                    continue
                trial_rel = trial_dir_rel(path.name, int(trial_path.name))
                trial = _run_entry(trial_rel, "trial", trial_path)
                if trial is not None:
                    entries[trial.rel_dir] = trial
    return entries


def _mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _newest(paths: Iterable[Path]) -> int:
    stamps = [stamp for stamp in (_mtime_ns(p) for p in paths) if stamp is not None]
    return max(stamps) if stamps else 0


def _run_entry(rel_dir: str, kind: EntryKind, path: Path) -> DiskEntry | None:
    manifest = path / RUN_MANIFEST_FILENAME
    outcome = path / RUN_OUTCOME_FILENAME
    if not manifest.is_file() and not outcome.is_file():
        return None
    key = _run_key(path, manifest, outcome)
    stamp = _newest((manifest, outcome, path / RUN_ANNOTATIONS_FILENAME))
    return DiskEntry(rel_dir, kind, path, key, stamp)


def _run_key(path: Path, manifest: Path, outcome: Path) -> str:
    """Return the id the directory carries: the sealed ``sim_id``, else the ``attempt_id``."""
    try:
        if manifest.is_file():
            return f"sim:{read_json(manifest)['run']['sim_id']}"
        return f"attempt:{read_json(outcome)['attempt_id']}"
    except (OSError, ValueError, KeyError, TypeError):
        # An unreadable file is re-read on every pass, and reported then.
        return f"unreadable:{uuid4().hex}"


def _session_entry(rel_dir: str, path: Path) -> DiskEntry | None:
    descriptor = path / SESSION_DESCRIPTOR_FILENAME
    outcome = path / RUN_OUTCOME_FILENAME
    if not descriptor.is_file() and not outcome.is_file():
        return None
    try:
        if descriptor.is_file():
            key = f"session:{read_json(descriptor)['session_id']}"
        else:
            key = f"attempt:{read_json(outcome)['attempt_id']}"
    except (OSError, ValueError, KeyError, TypeError):
        key = f"unreadable:{uuid4().hex}"
    phases = path / SESSION_PHASES_DIRNAME
    phase_files = list(phases.glob(f"*/{SESSION_DESCRIPTOR_FILENAME}")) if phases.is_dir() else []
    stamp = _newest((descriptor, outcome, path / SESSION_TRIALS_FILENAME, *phase_files))
    return DiskEntry(rel_dir, "session", path, key, stamp)


# ---------------------------------------------------------------------------
# Writing the index
# ---------------------------------------------------------------------------


def known_issues_digest() -> str:
    """Return a digest of the known issues register this build labels with."""
    payload = json.dumps(
        [issue.model_dump(mode="json") for issue in load_known_issues()], sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _index_is_of_this_build(index_path: Path) -> bool:
    """Return whether the index at ``index_path`` has this schema and these labelling rules."""
    if not index_path.is_file():
        return False
    try:
        connection = connect_with_retry(str(index_path), read_only=True)
    except Exception as exc:  # noqa: BLE001 - an unreadable index is rebuilt, not repaired
        logger.warning("Index at %s cannot be opened, it is rebuilt: %s", index_path, exc)
        return False
    try:
        if read_index_schema_version(connection) != INDEX_SCHEMA_VERSION:
            return False
        stamped = dict(
            connection.execute(
                f"SELECT key, value FROM {INDEX_META_TABLE} WHERE key IN (?, ?)",
                [META_RULE_VERSION, META_KNOWN_ISSUES_DIGEST],
            ).fetchall()
        )
    finally:
        connection.close()
    return stamped == {
        META_RULE_VERSION: RULE_VERSION,
        META_KNOWN_ISSUES_DIGEST: known_issues_digest(),
    }


def _read_indexed(index_path: Path) -> dict[str, tuple[str, int]]:
    """Return ``{rel_dir: (source_key, source_mtime_ns)}`` of the cases the index holds."""
    connection = connect_with_retry(str(index_path), read_only=True)
    try:
        rows = connection.execute(
            "SELECT rel_dir, source_key, source_mtime_ns FROM cases"
        ).fetchall()
    finally:
        connection.close()
    return {str(rel): (str(key), int(stamp)) for rel, key, stamp in rows}


def _write_index(
    root: Path,
    disk: dict[str, DiskEntry],
    *,
    incremental: bool,
    changed: set[str] | None = None,
    removed: set[str] | None = None,
) -> IndexReport:
    index_path = catalog_path_for(root)
    staging = index_path.with_name(f"{index_path.name}.rebuild-{uuid4().hex[:8]}")
    staging.parent.mkdir(parents=True, exist_ok=True)
    indexed_at = datetime.now(UTC)
    to_write = sorted(changed) if incremental and changed is not None else sorted(disk)
    to_remove = sorted(removed or ()) if incremental else []

    written: list[str] = []
    sessions: list[str] = []
    skipped: list[SkippedEntry] = []
    rows: dict[str, int] = {}

    try:
        if incremental:
            shutil.copy2(index_path, staging)
        connection = connect_with_retry(str(staging))
        try:
            if not incremental:
                create_index_schema(connection, hydromodpy_version=__version__)
            writer = _IndexWriter(connection, root, indexed_at)
            for rel_dir in to_remove:
                writer.forget(rel_dir)
            for rel_dir in to_write:
                entry = disk[rel_dir]
                if incremental:
                    writer.forget(rel_dir)
                try:
                    counts = writer.index_entry(entry)
                except Exception as exc:  # noqa: BLE001 - one bad directory never aborts a pass
                    logger.warning("index left out %s: %s", rel_dir, exc)
                    writer.forget(rel_dir)
                    skipped.append(SkippedEntry(rel_dir, str(exc)))
                    continue
                (sessions if entry.kind == "session" else written).append(rel_dir)
                for table, count in counts.items():
                    rows[table] = rows.get(table, 0) + count
            writer.refresh_sites()
            ensure_views(connection)
            writer.stamp()
            connection.execute("CHECKPOINT")
        finally:
            connection.close()
        _publish(staging, index_path)
        _forget_write_ahead_log(index_path)
    finally:
        _discard(staging)
    logger.info(
        "indexed %d run(s), %d session(s), removed %d into %s",
        len(written),
        len(sessions),
        len(to_remove),
        index_path,
    )
    return IndexReport(
        index_path=index_path,
        full=not incremental,
        indexed=tuple(written),
        sessions=tuple(sessions),
        removed=tuple(to_remove),
        skipped=tuple(skipped),
        rows=rows,
    )


class _IndexWriter:
    """Write the rows of one directory into an index being built."""

    def __init__(self, connection: duckdb.DuckDBPyConnection, root: Path, indexed_at: datetime):
        self._conn = connection
        self._root = root
        self._at = indexed_at
        self._columns: dict[str, list[str]] = {}

    # -- bookkeeping -----------------------------------------------------------

    def stamp(self) -> None:
        """Record when the pass ran and which labelling build it labelled with."""
        self._conn.execute(
            f"INSERT OR REPLACE INTO {INDEX_META_TABLE} (key, value) VALUES (?, ?), (?, ?), (?, ?)",
            [
                META_INDEXED_AT,
                self._at.isoformat(),
                META_RULE_VERSION,
                RULE_VERSION,
                META_KNOWN_ISSUES_DIGEST,
                known_issues_digest(),
            ],
        )

    def columns_of(self, table: str) -> list[str]:
        if table not in self._columns:
            rows = self._conn.execute(f"DESCRIBE {table}").fetchall()
            self._columns[table] = [str(row[0]) for row in rows]
        return self._columns[table]

    def insert(self, table: str, row: dict[str, Any]) -> None:
        names = [name for name in self.columns_of(table) if name in row]
        placeholders = ", ".join("?" for _ in names)
        self._conn.execute(
            f"INSERT INTO {table} ({', '.join(names)}) VALUES ({placeholders})",
            [row[name] for name in names],
        )

    def forget(self, rel_dir: str) -> None:
        """Remove every row the index holds for ``rel_dir``."""
        sims = self._conn.execute(
            "SELECT CAST(sim_id AS VARCHAR) FROM simulations WHERE rel_dir = ?", [rel_dir]
        ).fetchall()
        for (sim_id,) in sims:
            for table in SIMULATION_CHILD_TABLES:
                self._conn.execute(f"DELETE FROM {table} WHERE sim_id = ?", [sim_id])
            self._conn.execute("DELETE FROM simulations WHERE sim_id = ?", [sim_id])
        sessions = self._conn.execute(
            "SELECT session_id FROM calibration_sessions WHERE rel_dir = ?", [rel_dir]
        ).fetchall()
        for (session_id,) in sessions:
            for table in SESSION_CHILD_TABLES:
                self._conn.execute(f"DELETE FROM {table} WHERE session_id = ?", [session_id])
            self._conn.execute(
                "DELETE FROM calibration_sessions WHERE session_id = ?", [session_id]
            )
        self._conn.execute("DELETE FROM attempts WHERE rel_dir = ?", [rel_dir])
        self._conn.execute("DELETE FROM cases WHERE rel_dir = ?", [rel_dir])

    def refresh_sites(self) -> None:
        """Count the cases and sealed runs of every site, and drop the empty ones."""
        self._conn.execute(
            "INSERT INTO sites (site, n_cases, n_runs) "
            "SELECT DISTINCT site, 0, 0 FROM cases "
            "WHERE site IS NOT NULL AND site NOT IN (SELECT site FROM sites)"
        )
        self._conn.execute(
            "UPDATE sites SET "
            "n_cases = (SELECT COUNT(DISTINCT c.case_id) FROM cases c WHERE c.site = sites.site), "
            "n_runs = (SELECT COUNT(*) FROM simulations s WHERE s.site = sites.site)"
        )
        self._conn.execute("DELETE FROM sites WHERE n_cases = 0 AND n_runs = 0")

    # -- one directory ---------------------------------------------------------

    def index_entry(self, entry: DiskEntry) -> dict[str, int]:
        if entry.kind == "session":
            return self._index_session(entry)
        return self._index_run(entry)

    def _index_run(self, entry: DiskEntry) -> dict[str, int]:
        path = entry.path
        outcome = read_outcome(path)
        sealed = (path / RUN_MANIFEST_FILENAME).is_file()
        if outcome is None and not sealed:
            raise ValueError(f"neither {RUN_OUTCOME_FILENAME} nor {RUN_MANIFEST_FILENAME}")
        status = effective_status(path, now=self._at)
        counts: dict[str, int] = {}
        manifest: Manifest | None = None
        if sealed:
            manifest = Manifest.model_validate(read_manifest(path))
            counts.update(self._index_seal(entry, manifest))
        run = manifest.run if manifest is not None else None
        site = manifest.site.name if manifest is not None and manifest.site else None
        beat = read_heartbeat(path)
        case: dict[str, Any] = {
            "rel_dir": entry.rel_dir,
            "kind": entry.kind,
            "case_id": run.case_id if run is not None else outcome.case_id,
            "site": site if site is not None else (outcome.site if outcome else None),
            "recipe": run.recipe if run is not None else None,
            "project": run.project if run is not None else (outcome.project if outcome else None),
            "sim_id": run.sim_id if run is not None else (outcome.sim_id if outcome else None),
            "attempt": outcome.attempt if outcome else run.attempt,
            "attempt_id": outcome.attempt_id if outcome else run.attempt_id,
            "status": status,
            "heartbeat_at": None if beat is None else beat.at,
            "source_key": entry.key,
            "source_mtime_ns": entry.mtime_ns,
            "indexed_at": self._at,
        }
        if outcome is not None:
            case.update(_outcome_columns(outcome))
        elif run is not None:
            case.update({"started_at": run.started_at, "ended_at": run.ended_at})
        self.insert("cases", case)
        counts["cases"] = 1
        counts["attempts"] = self._index_attempts(entry, outcome)
        return counts

    def _index_attempts(self, entry: DiskEntry, current: Outcome | None) -> int:
        outcomes: list[Outcome] = [] if current is None else [current]
        attempts_dir = entry.path / RUN_ATTEMPTS_DIRNAME
        if attempts_dir.is_dir():
            for earlier in sorted(attempts_dir.iterdir()):
                if earlier.is_dir():
                    previous = read_outcome(earlier)
                    if previous is not None:
                        outcomes.append(previous)
        seen: set[str] = set()
        count = 0
        for outcome in outcomes:
            if outcome.attempt_id in seen:
                continue
            seen.add(outcome.attempt_id)
            row = {
                "rel_dir": entry.rel_dir,
                "attempt": outcome.attempt,
                "attempt_id": outcome.attempt_id,
                "case_id": outcome.case_id,
                "sim_id": outcome.sim_id,
                "status": outcome.status,
                **_outcome_columns(outcome),
            }
            self.insert("attempts", row)
            count += 1
        return count

    def _index_seal(self, entry: DiskEntry, manifest: Manifest) -> dict[str, int]:
        path = entry.path
        tables_dir = path / TABLES_DIRNAME
        snapshot = tables_dir / f"{SIMULATION_TABLE_NAME}{PARQUET_FILE_SUFFIX}"
        if not snapshot.is_file():
            raise FileNotFoundError(
                f"no {snapshot.name} under {TABLES_DIRNAME}: the run carries a manifest "
                "but not the index row it seals"
            )
        rows = pq.read_table(snapshot).to_pylist()
        if len(rows) != 1:
            raise ValueError(f"{snapshot.name} holds {len(rows)} rows, one run has one")
        row = dict(rows[0])
        sim_id = str(manifest.run.sim_id)
        if str(row.get("sim_id")) != sim_id:
            raise ValueError(
                f"{RUN_MANIFEST_FILENAME} names sim {sim_id[:8]} but {snapshot.name} holds "
                f"{str(row.get('sim_id'))[:8]}: the run directory mixes two identities"
            )
        row.update(_directory_identity(entry, manifest))
        row.update(_lookup_ids(self._conn, row))
        row.update(_frozen_config(path))
        row.update(_label_columns(manifest, label_date=self._at.date()))
        row.update(_score_columns(manifest))
        row["session_id"] = manifest.lineage.session_id
        self.insert("simulations", row)
        counts = {"simulations": 1}
        counts["parameters"] = self._insert_parameters(sim_id, manifest)
        counts["metrics"] = self._insert_metrics(sim_id, manifest)
        counts["tracked_files"] = self._insert_tracked_files(sim_id, manifest)
        counts["geographic_metadata"] = self._insert_geographic_metadata(sim_id, manifest)
        counts["geographic_features"] = self._insert_geographic_features(sim_id, tables_dir)
        counts["provenance"] = self._insert_provenance(
            sim_id, tables_dir / f"provenance{PARQUET_FILE_SUFFIX}"
        )
        counts["runs_environment"] = self._insert_environment(sim_id, path, manifest)
        counts.update(self._insert_annotations(sim_id, path))
        if manifest.site is not None:
            self._upsert_site(manifest)
        return counts

    def _insert_parameters(self, sim_id: str, manifest: Manifest) -> int:
        for parameter in manifest.parameters:
            self.insert(
                "parameters",
                {
                    "sim_id": sim_id,
                    "param_name": parameter.name,
                    "zone_id": parameter.zone,
                    "value": parameter.value,
                    "unit": parameter.unit,
                    "parameterization": parameter.parameterization,
                    "valid_from": manifest.run.created_at,
                    "origin": parameter.origin,
                    "calibrated": parameter.calibrated,
                },
            )
        return len(manifest.parameters)

    def _insert_metrics(self, sim_id: str, manifest: Manifest) -> int:
        for metric in manifest.metrics:
            self.insert(
                "metrics",
                {
                    "sim_id": sim_id,
                    "station_id": metric.station,
                    "variable": metric.variable,
                    "metric_name": metric.metric,
                    "value": metric.value,
                    "n_samples": metric.nse_n,
                    "nse_window_start": metric.nse_window_start,
                    "nse_window_end": metric.nse_window_end,
                    "nse_n": metric.nse_n,
                    "metric_rule_version": metric.metric_rule_version,
                },
            )
        return len(manifest.metrics)

    def _insert_tracked_files(self, sim_id: str, manifest: Manifest) -> int:
        for entry in manifest.inputs:
            self.insert(
                "tracked_files",
                {
                    "sim_id": sim_id,
                    "role": entry.role,
                    "category": entry.category,
                    "original_path": entry.declared_path,
                    "canonical_path": entry.path,
                    "sha256": entry.sha256,
                    "size_bytes": entry.bytes,
                    "portable": entry.portable,
                    "recorded_at": manifest.sealed_at,
                },
            )
        return len(manifest.inputs)

    def _insert_geographic_metadata(self, sim_id: str, manifest: Manifest) -> int:
        catchment = manifest.geometry.catchment
        for key, value in catchment.items():
            self.insert(
                "geographic_metadata",
                {
                    "sim_id": sim_id,
                    "key": str(key),
                    "value": None if value is None else str(value),
                    "value_type": _python_value_type(value),
                },
            )
        return len(catchment)

    def _insert_geographic_features(self, sim_id: str, tables_dir: Path) -> int:
        payloads = sorted(tables_dir.glob(f"{GEOGRAPHIC_FEATURE_PREFIX}*{PARQUET_FILE_SUFFIX}"))
        for payload in payloads:
            feature_name = payload.name[len(GEOGRAPHIC_FEATURE_PREFIX) : -len(PARQUET_FILE_SUFFIX)]
            geometry_kind, crs, properties = _describe_geoparquet(payload)
            self.insert(
                "geographic_features",
                {
                    "sim_id": sim_id,
                    "feature_name": feature_name,
                    "geometry_kind": geometry_kind,
                    "crs_wkt": crs,
                    "geoparquet_path": encode_workspace_path(self._root, payload),
                    "properties": json.dumps(properties),
                },
            )
        return len(payloads)

    def _insert_provenance(self, sim_id: str, payload: Path) -> int:
        if not payload.is_file():
            return 0
        count = 0
        for row in pq.read_table(payload).to_pylist():
            record = dict(row)
            record["sim_id"] = sim_id
            self.insert("provenance", record)
            count += 1
        return count

    def _insert_environment(self, sim_id: str, path: Path, manifest: Manifest) -> int:
        target = path / RUN_PROVENANCE_FILENAME
        if not target.is_file():
            return 0
        provenance = RunProvenance.model_validate(read_json(target))
        host = provenance.platform
        git = provenance.git
        solver = provenance.solver
        environment = provenance.environment
        self.insert(
            "runs_environment",
            {
                "sim_id": sim_id,
                "python_version": provenance.python.get("version"),
                "hydromodpy_version": provenance.tool.get("version"),
                "platform": host.get("platform"),
                "hostname": host.get("hostname"),
                "user_name": host.get("user"),
                "cpu_info": json.dumps(host.get("cpu") or {}),
                "memory_gb": host.get("memory_gb"),
                "git_commit": git.get("commit"),
                "git_dirty": git.get("dirty"),
                "project_git_commit": git.get("project_commit"),
                "solver_name": solver.get("name"),
                "solver_engine": solver.get("engine"),
                "solver_execution_mode": solver.get("execution_mode"),
                "solver_binary_path": solver.get("binary_path"),
                "solver_binary_sha256": solver.get("binary_sha256"),
                "solver_version_text": solver.get("version"),
                "conda_env_hash": environment.get("conda_env_hash"),
                "env_packages": json.dumps(environment.get("packages_frozen") or []),
                "rng_seed": environment.get("rng_seed"),
                "recorded_at": manifest.sealed_at,
            },
        )
        return 1

    def _insert_annotations(self, sim_id: str, path: Path) -> dict[str, int]:
        annotations = read_annotations(path)
        for tag in annotations.tags:
            self.insert("tags", {"sim_id": sim_id, "tag": tag})
        for note in annotations.notes:
            self.insert(
                "sim_notes",
                {
                    "sim_id": sim_id,
                    "note": note.text,
                    "added_at": note.at,
                    "added_by": note.author,
                },
            )
        return {"tags": len(annotations.tags), "sim_notes": len(annotations.notes)}

    def _upsert_site(self, manifest: Manifest) -> None:
        site = manifest.site
        assert site is not None
        self._conn.execute(
            "INSERT OR REPLACE INTO sites (site, site_fingerprint, label, gauge, uri, x_outlet, "
            "y_outlet, crs, area_km2, dem_resolution_m, n_cases, n_runs) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)",
            [
                site.name,
                site.fingerprint,
                site.label,
                site.gauge,
                site.uri,
                site.x_outlet,
                site.y_outlet,
                site.crs,
                site.area_km2,
                site.dem_resolution_m,
            ],
        )

    # -- one session -----------------------------------------------------------

    def _index_session(self, entry: DiskEntry) -> dict[str, int]:
        path = entry.path
        descriptor: SessionDescriptor | None = None
        if (path / SESSION_DESCRIPTOR_FILENAME).is_file():
            descriptor = read_session(path)
        outcome = read_outcome(path)
        if descriptor is None and outcome is None:
            raise ValueError(f"neither {SESSION_DESCRIPTOR_FILENAME} nor {RUN_OUTCOME_FILENAME}")
        counts: dict[str, int] = {}
        if descriptor is not None:
            counts.update(self._insert_session(entry, descriptor, outcome))
            status = descriptor.status
            if status == "running":
                status = effective_status(path, now=self._at) if outcome is not None else "running"
                if status not in ("running", "stale"):
                    status = "running"
        else:
            status = effective_status(path, now=self._at)
        beat = read_heartbeat(path)
        case: dict[str, Any] = {
            "rel_dir": entry.rel_dir,
            "kind": "session",
            "case_id": descriptor.case_id if descriptor is not None else outcome.case_id,
            "site": descriptor.site if descriptor is not None else outcome.site,
            "project": outcome.project if outcome is not None else None,
            "sim_id": (
                descriptor.best.sim_id
                if descriptor is not None and descriptor.best is not None
                else (outcome.sim_id if outcome is not None else None)
            ),
            "status": status,
            "heartbeat_at": None if beat is None else beat.at,
            "source_key": entry.key,
            "source_mtime_ns": entry.mtime_ns,
            "indexed_at": self._at,
        }
        if outcome is not None:
            case.update(_outcome_columns(outcome))
            case["attempt"] = outcome.attempt
            case["attempt_id"] = outcome.attempt_id
        elif descriptor is not None:
            case["started_at"] = descriptor.started_at
            case["ended_at"] = descriptor.ended_at
        self.insert("cases", case)
        counts["cases"] = 1
        counts["attempts"] = self._index_attempts(entry, outcome)
        return counts

    def _insert_session(
        self, entry: DiskEntry, descriptor: SessionDescriptor, outcome: Outcome | None
    ) -> dict[str, int]:
        trials = read_trials(entry.path)
        phases = list_phases(entry.path)
        best = descriptor.best
        window = descriptor.objective_window
        self.insert(
            "calibration_sessions",
            {
                "session_id": descriptor.session_id,
                "rel_dir": entry.rel_dir,
                "site": descriptor.site,
                "case_id": descriptor.case_id,
                "project": outcome.project if outcome is not None else None,
                "config_hash": descriptor.config_hash,
                "hydromodpy_version": descriptor.hydromodpy_version,
                "method": descriptor.method,
                "search_space": json.dumps(descriptor.search_space, default=str),
                "objective_name": descriptor.objective_name,
                "objective_window_start": None if window is None else window.start,
                "objective_window_end": None if window is None else window.end,
                "n_trials": len(trials),
                "best_trial": None if best is None else best.trial,
                "best_sim_id": None if best is None else best.sim_id,
                "best_rel_dir": None if best is None else best.rel_dir,
                "best_objective": None if best is None else best.objective,
                "status": descriptor.status,
                "started_at": descriptor.started_at,
                "ended_at": descriptor.ended_at,
                "error_message": descriptor.error_message,
                "root_search": (
                    None if descriptor.root_search is None else json.dumps(descriptor.root_search)
                ),
            },
        )
        for phase in phases:
            phase_best = phase.best
            self.insert(
                "calibration_phases",
                {
                    "session_id": descriptor.session_id,
                    "phase_id": phase.phase_id,
                    "name": phase.name,
                    "phase_index": phase.index,
                    "status": phase.status,
                    "frozen": json.dumps(phase.frozen, default=str),
                    "best_trial": None if phase_best is None else phase_best.trial,
                    "best_sim_id": None if phase_best is None else phase_best.sim_id,
                    "best_objective": None if phase_best is None else phase_best.objective,
                    "restarts": phase.restarts,
                },
            )
        for trial in trials:
            self.insert(
                "calibration_iterations",
                {
                    "session_id": descriptor.session_id,
                    "trial": trial.trial,
                    "phase": trial.phase,
                    "restart": trial.restart,
                    "params": json.dumps(trial.params, default=str),
                    "params_hash": trial.params_hash,
                    "objective": trial.objective,
                    "metrics": json.dumps(trial.metrics, default=str),
                    "status": trial.status,
                    "started_at": trial.started_at,
                    "ended_at": trial.ended_at,
                    "sim_id": trial.sim_id,
                    "rel_dir": trial.rel_dir,
                },
            )
        return {
            "calibration_sessions": 1,
            "calibration_phases": len(phases),
            "calibration_iterations": len(trials),
        }


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------


def _outcome_columns(outcome: Outcome) -> dict[str, Any]:
    """The columns of ``cases`` and ``attempts`` an outcome fills."""
    return {
        "started_at": outcome.started_at,
        "ended_at": outcome.ended_at,
        "host": outcome.host,
        "pid": outcome.pid,
        "step": outcome.step,
        "exit_code": outcome.exit_code,
        "signal": outcome.signal,
        "written_by": outcome.written_by,
        "error_type": None if outcome.error is None else outcome.error.type,
        "error_message": None if outcome.error is None else outcome.error.message,
    }


def _directory_identity(entry: DiskEntry, manifest: Manifest) -> dict[str, Any]:
    """Name the run after its directory: the tree is what the name is."""
    if entry.kind == "run":
        name = entry.path.name
        stem, version = split_stem_version(name)
        return {
            "name": name,
            "name_stem": stem,
            "version_int": version or 1,
            "rel_dir": entry.rel_dir,
        }
    run = manifest.run
    return {
        "name": run.name,
        "name_stem": run.name_stem,
        "version_int": run.version,
        "rel_dir": entry.rel_dir,
    }


def _lookup_ids(connection: duckdb.DuckDBPyConnection, row: dict[str, Any]) -> dict[str, Any]:
    """Resolve the dimension codes of a row into their ids."""

    def _id(table: str, code: Any) -> int | None:
        if code is None:
            return None
        found = connection.execute(f"SELECT id FROM {table} WHERE code = ?", [str(code)]).fetchone()
        return None if found is None else int(found[0])

    solver_id = _id("solvers", row.get("solver"))
    if solver_id is None:
        raise ValueError(f"unknown solver code {row.get('solver')!r}")
    return {
        "solver_id": solver_id,
        "status_id": _id("statuses", "completed"),
        "flow_regime_id": _id("flow_regimes", row.get("flow_regime")),
        "mesh_topology_id": _id("mesh_topologies", row.get("mesh_topology")),
    }


def _frozen_config(path: Path) -> dict[str, Any]:
    """The frozen configuration of the run, as text and as JSON."""
    target = path / RUN_CONFIG_FILENAME
    if not target.is_file():
        return {"config_toml": None, "config_snapshot": None}
    text = target.read_text(encoding="utf-8")
    try:
        snapshot = json.dumps(tomllib.loads(text), default=str)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{RUN_CONFIG_FILENAME} is not valid TOML: {exc}") from exc
    return {"config_toml": text, "config_snapshot": snapshot}


def _label_columns(manifest: Manifest, *, label_date) -> dict[str, Any]:
    """The label of the run today, computed from its sealed checks."""
    result = label_of(manifest)
    return {
        "label": result.label,
        "label_date": label_date,
        "rule_version": result.rule_version,
        "label_reasons": "; ".join(result.reasons) if result.reasons else None,
        "known_issues": ",".join(result.known_issues) if result.known_issues else None,
    }


def _score_columns(manifest: Manifest) -> dict[str, Any]:
    """Where the headline score of the run was read, from its seal."""
    score = manifest.score
    return {
        "nse_station": None if score is None else score.station,
        "nse_variable": None if score is None else score.variable,
    }


def _python_value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "double"
    return "string"


_GEOMETRY_KINDS: dict[str, str] = {
    "point": "point",
    "multipoint": "point",
    "linestring": "linestring",
    "multilinestring": "linestring",
    "polygon": "polygon",
    "multipolygon": "multipolygon",
}


def _describe_geoparquet(payload: Path) -> tuple[str | None, str, dict[str, Any]]:
    """Return ``(geometry_kind, crs, properties)`` of a GeoParquet feature layer."""
    from shapely.ops import unary_union

    from hydromodpy.core.io.geoparquet import read_geoparquet

    gdf = read_geoparquet(payload)
    if gdf.crs is None:
        raise ValueError(f"{payload.name} carries no CRS")
    union = unary_union([g for g in gdf.geometry if g is not None and not g.is_empty])
    geometry_kind = _GEOMETRY_KINDS.get(str(union.geom_type).lower())
    crs = gdf.crs.to_string()
    schema_payload = {
        "columns": [str(col) for col in gdf.columns if col != gdf.geometry.name],
        "geometry_kind": geometry_kind,
        "crs": crs,
    }
    properties = {
        "n_features": int(len(gdf)),
        "bbox": [float(value) for value in gdf.total_bounds],
        "geometry_encoding": "WKB",
        "schema_sha256": hashlib.sha256(
            json.dumps(schema_payload, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "geoparquet_version": "1.1.0",
    }
    return geometry_kind, crs, properties


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------


def _publish(staging: Path, index_path: Path) -> None:
    """Install the staged database at ``index_path`` in one filesystem step."""
    try:
        rename_over_open_file(staging, index_path)
    except OSError as refused:
        raise OSError(
            f"Could not publish the index at {index_path}: {refused}. "
            "The previous index is untouched and still readable; close the "
            "processes reading this project and index again."
        ) from refused


def _forget_write_ahead_log(index_path: Path) -> None:
    """Drop the write-ahead log of the index that was just replaced."""
    wal_path = index_path.with_name(f"{index_path.name}.wal")
    try:
        wal_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Left the stale write-ahead log %s behind: %s", wal_path, exc)


def _discard(staging: Path) -> None:
    """Remove the staging database and its companions."""
    for suffix in ("", ".wal", ".lock"):
        staging.with_name(f"{staging.name}{suffix}").unlink(missing_ok=True)


__all__ = [
    "DiskEntry",
    "GEOGRAPHIC_FEATURE_PREFIX",
    "IndexReport",
    "SkippedEntry",
    "index_is_current",
    "index_new_runs",
    "known_issues_digest",
    "rebuild_index",
    "scan_tree",
]
