"""Cache store: connection, schema bootstrap, register, frozen-mode helpers.

Concern: state-changing operations on raw catalog entries and the
file-system anchors that back them (workspace root, lockfile, sidecars).
"""

from __future__ import annotations

import time
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import encode_workspace_path
from hydromodpy.data.registry.constants import SENTINEL_CUSTOM, SENTINEL_EMPTY

if TYPE_CHECKING:
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

logger = get_logger(__name__)

_RETRY = 8
_BACKOFF = 0.05

#: Root of the installed ``hydromodpy`` package. Provenance sidecars are never
#: written next to read-only data bundled inside the package (e.g. example and
#: ``cases/`` reference inputs); those sidecars are version-controlled and must
#: not be mutated at runtime.
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _is_inside_package(path: Path) -> bool:
    try:
        Path(path).resolve().relative_to(_PACKAGE_ROOT)
    except ValueError:
        return False
    return True


def workspace_root(catalog: DataCatalogDuckDB) -> Path | None:
    """Return the workspace root inferred from the cache DB location."""
    if catalog._db_path is None:
        return None
    return catalog._db_path.parent.parent


def encode_path_for_storage(catalog: DataCatalogDuckDB, file_path: Path | str) -> str:
    """Encode ``file_path`` as a workspace-relative POSIX string.

    Falls back to ``str(file_path)`` for the in-memory catalog or when
    the target lies outside every supported anchor (workspace,
    ``cache://``, ``state://``). Anchored encoding is delegated to
    :func:`hydromodpy.core.state.paths.encode_workspace_path` and is
    attempted first when a workspace is known.
    """
    workspace = workspace_root(catalog)
    if workspace is None:
        return str(file_path)
    try:
        return encode_workspace_path(workspace, Path(file_path))
    except ValueError:
        # Path lies outside every portable anchor; keep the raw string
        # so the catalog still records something useful for ad-hoc
        # imports of custom files (tests, exploratory usage).
        return str(file_path)


def resolve_entry_path(
    catalog: DataCatalogDuckDB,
    file_path: Path | str,
    *,
    variable: str | None = None,
) -> Path:
    path = Path(file_path)
    if path.is_absolute():
        return path
    candidates: list[Path] = []
    if catalog._db_path is not None:
        if variable:
            candidates.append(catalog._db_path.parent / variable / path)
        candidates.extend((catalog._db_path.parent / path, catalog._db_path.parent.parent / path))
    candidates.append(path)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def workspace_lockfile_path(catalog: DataCatalogDuckDB) -> Path | None:
    if catalog._db_path is None:
        return None
    from hydromodpy.data.data_freeze import LOCKFILE_NAME

    candidates = (
        catalog._db_path.parent.parent / LOCKFILE_NAME,
        catalog._db_path.parent / LOCKFILE_NAME,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def frozen_enabled() -> bool:
    from hydromodpy.data.data_freeze import is_frozen_mode

    return is_frozen_mode()


def locked_artifacts(catalog: DataCatalogDuckDB):
    lockfile = workspace_lockfile_path(catalog)
    if lockfile is None or not lockfile.is_file():
        raise RuntimeError("Frozen data mode requires an existing hydromodpy.lock file.")
    from hydromodpy.data.data_freeze import read_lockfile

    return read_lockfile(lockfile)


def match_locked_artifact(
    catalog: DataCatalogDuckDB,
    *,
    variable: str,
    source: str,
    station_id: str | None,
    file_path: Path | str,
):
    path = Path(file_path)
    resolved = resolve_entry_path(catalog, path, variable=variable)
    artifacts = locked_artifacts(catalog)
    for artifact in artifacts:
        if (
            artifact.variable == variable
            and artifact.source == source
            and artifact.station_id == station_id
            and (
                Path(artifact.file_path) == path
                or Path(artifact.file_path) == resolved
                or resolve_entry_path(catalog, artifact.file_path, variable=variable) == resolved
            )
        ):
            return artifact
    return None


def reject_frozen_cache_miss(
    catalog: DataCatalogDuckDB,
    *,
    variable: str,
    source: str,
    station_id: str | None,
) -> None:
    if not frozen_enabled():
        return
    locked_artifacts(catalog)
    raise RuntimeError(
        "Frozen data mode forbids cache misses: "
        f"{variable}/{source}/{station_id or '-'} is absent from the local catalog."
    )


def reject_frozen_entry_mismatch(catalog: DataCatalogDuckDB, entry) -> None:
    if not frozen_enabled():
        return
    artifact = match_locked_artifact(
        catalog,
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
    observed = entry.sha256 or sha256_or_none(
        resolve_entry_path(catalog, entry.file_path, variable=entry.variable)
    )
    if observed != artifact.sha256:
        raise RuntimeError(
            "Frozen data mode detected a SHA-256 mismatch for "
            f"{entry.variable}/{entry.source}/{entry.station_id or '-'}."
        )


def reject_frozen_register(
    catalog: DataCatalogDuckDB,
    *,
    variable: str,
    source: str,
    station_id: str | None,
    file_path: Path,
    file_sha256: str | None,
    is_custom: bool,
) -> None:
    if not frozen_enabled():
        return
    artifact = match_locked_artifact(
        catalog,
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


def register(
    catalog: DataCatalogDuckDB,
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
    resolved_path = resolve_entry_path(catalog, file_path, variable=variable)
    if file_mtime is None:
        try:
            mtime = resolved_path.stat().st_mtime if resolved_path.exists() else None
        except OSError:
            mtime = None
    else:
        mtime = file_mtime
    digest = file_sha256 or sha256_or_none(resolved_path)
    reject_frozen_register(
        catalog,
        variable=variable,
        source=source,
        station_id=station_id,
        file_path=file_path,
        file_sha256=digest,
        is_custom=is_custom,
    )

    ds = dt_to_str(date_start)
    de = dt_to_str(date_end)
    bx = bbox or (None, None, None, None)
    # P3 workspace-relative encoding: anchor portable file_path on the
    # workspace root (or cache://, state://). Falls back to ``str(path)``
    # for in-memory catalogs (workspace unknown).
    encoded_path = encode_path_for_storage(catalog, file_path)

    # P9 provenance sidecar: write a JSON sidecar next to every catalog
    # input so downstream tools have the upstream metadata even without
    # the DuckDB catalog around. Best-effort: failures stay non-fatal.
    if digest is not None and resolved_path.is_file():
        emit_input_sidecar(
            resolved_path,
            sha256=digest,
            source=source,
            crs=crs,
            bbox=bx,
        )

    backend = catalog.backend
    # Look for existing entry
    if station_id is not None:
        existing = backend.fetch_one(
            "SELECT id FROM entries WHERE variable = ? AND source = ? AND station_id = ?",
            [variable, source, station_id],
        )
    else:
        existing = backend.fetch_one(
            "SELECT id FROM entries WHERE variable = ? AND source = ? "
            "AND station_id IS NULL AND file_path = ?",
            [variable, source, encoded_path],
        )

    for attempt in range(_RETRY):
        try:
            if existing is not None:
                eid = existing[0]
                backend.execute(
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
                        is_custom,
                        json_or_none(fetch_metadata),
                        eid,
                    ],
                )
                return eid
            else:
                backend.execute(
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
                        is_custom,
                        json_or_none(fetch_metadata),
                    ],
                )
                row = backend.fetch_one("SELECT currval('entries_seq')")
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


# -- module-level utilities shared across the three sibling modules --------


def dt_to_str(dt: datetime | str | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def json_or_none(d: dict | None) -> str | None:
    if d is None:
        return None
    import json

    return json.dumps(d)


def sha256_or_none(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def emit_input_sidecar(
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

    Inputs that live inside the installed package tree (bundled example /
    ``cases/`` data) are skipped: their sidecars are committed and read-only.
    """
    if _is_inside_package(path):
        return
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


def try_unlink(fp: str) -> None:
    if fp in (SENTINEL_CUSTOM, SENTINEL_EMPTY):
        return
    try:
        p = Path(fp)
        if p.exists():
            p.unlink()
    except OSError as exc:
        logger.warning("Failed to delete file %s: %s", fp, exc)
