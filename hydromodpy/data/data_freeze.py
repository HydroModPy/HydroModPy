"""Lockfile helpers for reproducible input data (``hydromodpy.lock``).

A lockfile captures, for every variable+source pair currently indexed in
the input :class:`DataCatalogDuckDB`, the canonical URL, the SHA-256 of
the downloaded payload, the fetch timestamp and the on-disk mtime/size.

Frozen mode uses this lockfile to reject any mismatch: the cache becomes
read-only unless an exact SHA-256 match is produced.

This module only depends on :mod:`tomlkit` (already in the project's
dependencies) and the standard library. The archive/restore commands
create / unpack a portable ``tar.zst`` bundle containing the lockfile
and every indexed artefact.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tomlkit

from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

LOCKFILE_NAME = "hydromodpy.lock"
_LOCKFILE_VERSION = 1

# Process-wide frozen-mode flag. Consulted by data loaders to refuse
# fresh downloads when a lockfile is authoritative.
_FROZEN_MODE: bool = False


def set_frozen_mode(enabled: bool) -> None:
    """Toggle process-wide frozen mode (used by ``hmp run --frozen``)."""
    global _FROZEN_MODE
    _FROZEN_MODE = bool(enabled)


def is_frozen_mode() -> bool:
    """Return whether frozen mode is currently active."""
    return _FROZEN_MODE


@dataclass(frozen=True)
class LockedArtifact:
    """One locked artefact recorded in the lockfile."""

    variable: str
    source: str
    station_id: str | None
    file_path: str
    sha256: str
    file_mtime: float | None
    size_bytes: int | None
    fetched_at: str


@dataclass(frozen=True)
class LockMismatch:
    """Discrepancy between lockfile and catalog state."""

    kind: str  # "missing", "sha256", "size", "mtime"
    variable: str
    source: str
    station_id: str | None
    expected: Any
    observed: Any


# ---------------------------------------------------------------------- helpers


def sha256_of(path: Path, *, chunk: int = 64 * 1024) -> str:
    """Compute the SHA-256 digest of a file on disk."""
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for buf in iter(lambda: fh.read(chunk), b""):
            hasher.update(buf)
    return hasher.hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _catalog_base_dir(catalog: DataCatalogDuckDB) -> Path | None:
    db_path = getattr(catalog, "_db_path", None)
    if db_path is None:
        return None
    return Path(db_path).parent


def _resolve_artifact_path(
    file_path: str | Path,
    base_dir: Path | None,
    *,
    variable: str | None = None,
) -> Path:
    path = Path(file_path)
    if path.is_absolute():
        return path
    candidates: list[Path] = []
    if base_dir is not None:
        if variable:
            candidates.append(base_dir / variable / path)
        candidates.extend((base_dir / path, base_dir.parent / path))
    candidates.append(path)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _entry_to_locked(row: dict[str, Any], *, base_dir: Path | None) -> LockedArtifact | None:
    path = _resolve_artifact_path(row["file_path"], base_dir, variable=row.get("variable"))
    if not path.is_file():
        return None
    size = None
    try:
        size = path.stat().st_size
    except OSError:
        pass
    return LockedArtifact(
        variable=row["variable"],
        source=row["source"],
        station_id=row.get("station_id"),
        file_path=str(row["file_path"]),
        sha256=str(row.get("sha256") or sha256_of(path)),
        file_mtime=round(float(row["file_mtime"]), 6)
        if row.get("file_mtime") is not None
        else None,
        size_bytes=size,
        fetched_at=_now_iso(),
    )


# ---------------------------------------------------------------------- public


def write_lockfile(catalog: DataCatalogDuckDB, dest: Path | str) -> Path:
    """Freeze every cached artefact into *dest* (TOML)."""
    dest = Path(dest)
    rows = (
        catalog.connection.execute(
            "SELECT variable, source, station_id, file_path, file_mtime, sha256 "
            "FROM entries ORDER BY variable, source, station_id"
        )
        .fetchdf()
        .to_dict(orient="records")
    )

    doc = tomlkit.document()
    doc.add("version", _LOCKFILE_VERSION)
    doc.add("generated_at", _now_iso())
    artefacts = tomlkit.aot()
    base_dir = _catalog_base_dir(catalog)
    for row in rows:
        locked = _entry_to_locked(row, base_dir=base_dir)
        if locked is None:
            continue
        table = tomlkit.table()
        table.add("variable", locked.variable)
        table.add("source", locked.source)
        if locked.station_id is not None:
            table.add("station_id", locked.station_id)
        table.add("file_path", locked.file_path)
        table.add("sha256", locked.sha256)
        if locked.file_mtime is not None:
            table.add("file_mtime", locked.file_mtime)
        if locked.size_bytes is not None:
            table.add("size_bytes", locked.size_bytes)
        table.add("fetched_at", locked.fetched_at)
        artefacts.append(table)
    doc["artefact"] = artefacts

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(tomlkit.dumps(doc))
    return dest


def read_lockfile(path: Path | str) -> list[LockedArtifact]:
    """Load a lockfile from disk."""
    doc = tomlkit.parse(Path(path).read_text())
    out: list[LockedArtifact] = []
    for item in doc.get("artefact", []):
        out.append(
            LockedArtifact(
                variable=str(item["variable"]),
                source=str(item["source"]),
                station_id=(str(item["station_id"]) if "station_id" in item else None),
                file_path=str(item["file_path"]),
                sha256=str(item["sha256"]),
                file_mtime=(float(item["file_mtime"]) if "file_mtime" in item else None),
                size_bytes=(int(item["size_bytes"]) if "size_bytes" in item else None),
                fetched_at=str(item.get("fetched_at", "")),
            )
        )
    return out


def verify_frozen(
    catalog: DataCatalogDuckDB,
    lockfile: Path | str,
) -> list[LockMismatch]:
    """Return every mismatch between *lockfile* and the catalog state."""
    locked = {
        (la.variable, la.source, la.station_id, la.file_path): la for la in read_lockfile(lockfile)
    }
    mismatches: list[LockMismatch] = []
    base_dir = _catalog_base_dir(catalog)
    rows = catalog.connection.execute(
        "SELECT variable, source, station_id, file_path FROM entries"
    ).fetchall()
    seen = set()
    for variable, source, station_id, file_path in rows:
        key = (variable, source, station_id, file_path)
        seen.add(key)
        la = locked.get(key)
        if la is None:
            mismatches.append(
                LockMismatch(
                    kind="missing",
                    variable=variable,
                    source=source,
                    station_id=station_id,
                    expected=None,
                    observed=file_path,
                )
            )
            continue
        p = _resolve_artifact_path(file_path, base_dir, variable=variable)
        if not p.is_file():
            mismatches.append(
                LockMismatch(
                    kind="missing",
                    variable=variable,
                    source=source,
                    station_id=station_id,
                    expected=la.sha256,
                    observed=None,
                )
            )
            continue
        actual_sha = sha256_of(p)
        if actual_sha != la.sha256:
            mismatches.append(
                LockMismatch(
                    kind="sha256",
                    variable=variable,
                    source=source,
                    station_id=station_id,
                    expected=la.sha256,
                    observed=actual_sha,
                )
            )
    for key, la in locked.items():
        if key not in seen:
            mismatches.append(
                LockMismatch(
                    kind="missing",
                    variable=la.variable,
                    source=la.source,
                    station_id=la.station_id,
                    expected=la.sha256,
                    observed=None,
                )
            )
    return mismatches


# --------------------------------------------------------------------- archive


def _open_writer(dest: Path):
    if dest.suffix == ".zst":
        try:
            import zstandard as zstd  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "zstandard is required to create .tar.zst archives; "
                "use a .tar.gz suffix or install zstandard."
            ) from exc
        raw = open(dest, "wb")
        cctx = zstd.ZstdCompressor(level=3)
        return cctx.stream_writer(raw), raw, "w|"
    if dest.suffix in (".gz", ".tgz"):
        return open(dest, "wb"), None, "w:gz"
    return open(dest, "wb"), None, "w"


def _open_reader(src: Path):
    if src.suffix == ".zst":
        try:
            import zstandard as zstd  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("zstandard is required to read .tar.zst archives.") from exc
        raw = open(src, "rb")
        dctx = zstd.ZstdDecompressor()
        return dctx.stream_reader(raw), raw, "r|"
    if src.suffix in (".gz", ".tgz"):
        return open(src, "rb"), None, "r:gz"
    return open(src, "rb"), None, "r"


def archive_lockfile(
    catalog: DataCatalogDuckDB,
    dest: Path | str,
    *,
    lockfile_dest: Path | str | None = None,
) -> Path:
    """Produce an archive containing the lockfile and every artefact."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    lockfile_dest = Path(lockfile_dest) if lockfile_dest else (dest.parent / LOCKFILE_NAME)
    write_lockfile(catalog, lockfile_dest)

    stream, raw, mode = _open_writer(dest)
    try:
        with tarfile.open(fileobj=stream, mode=mode) as tar:
            tar.add(lockfile_dest, arcname=LOCKFILE_NAME)
            base_dir = _catalog_base_dir(catalog)
            for fp, variable in catalog.connection.execute(
                "SELECT file_path, variable FROM entries"
            ).fetchall():
                p = _resolve_artifact_path(fp, base_dir, variable=variable)
                if p.is_file():
                    tar.add(p, arcname=f"artefacts/{sha256_of(p)}/{p.name}")
    finally:
        if hasattr(stream, "close"):
            stream.close()
        if raw is not None:
            raw.close()
    return dest


def restore_archive(archive: Path | str, dest_dir: Path | str) -> Path:
    """Extract *archive* into *dest_dir* and verify SHA-256."""
    archive = Path(archive)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    stream, raw, mode = _open_reader(archive)
    try:
        with tarfile.open(fileobj=stream, mode=mode) as tar:
            tar.extractall(dest_dir, filter="data")
    finally:
        if hasattr(stream, "close"):
            stream.close()
        if raw is not None:
            raw.close()

    lockfile_path = dest_dir / LOCKFILE_NAME
    if lockfile_path.is_file():
        locked = read_lockfile(lockfile_path)
        for la in locked:
            candidate = dest_dir / "artefacts" / la.sha256 / Path(la.file_path).name
            if candidate.is_file():
                actual = sha256_of(candidate)
                if actual != la.sha256:
                    raise RuntimeError(
                        f"SHA-256 mismatch after restore: {candidate} "
                        f"expected {la.sha256}, got {actual}"
                    )
    return dest_dir


__all__ = [
    "LOCKFILE_NAME",
    "LockedArtifact",
    "LockMismatch",
    "sha256_of",
    "write_lockfile",
    "read_lockfile",
    "verify_frozen",
    "archive_lockfile",
    "restore_archive",
    "set_frozen_mode",
    "is_frozen_mode",
]


# Silence unused-import warnings from linters until this API is exercised
# more broadly by upcoming frozen-mode code paths.
_ = io
