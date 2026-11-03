"""Write, verify and archive ``hydromodpy.lock`` from the cache index.

The format and its readers live in :mod:`hydromodpy.data.provenance.lockfile`;
this module is the half that needs the catalog.

Writes are atomic: payload lands in a sibling ``<dest>.tmp.<uuid>`` file
which is ``fsync``'d before ``os.replace`` swaps it into place. A crash
mid-write leaves the previous lockfile untouched.

Verification has two modes:

- ``verify_frozen`` (used by ``hmp dev lock verify`` and the frozen-mode catalog)
  walks every entry and reports :class:`LockMismatch` records (one per kind:
  ``"missing"``, ``"sha256"``).
- ``verify_inputs_strict`` returns the same kind of report for the files the
  lockfile names, and is consumed by ``hmp dev lock verify --strict`` and
  ``hmp run --frozen`` to map a mismatch to a non-zero exit.
"""

from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tomlkit

from hydromodpy.core.exceptions import CacheCorruptionError
from hydromodpy.core.version import __version__ as _HMP_VERSION
from hydromodpy.data.provenance.lockfile import (
    LOCKFILE_NAME,
    LOCKFILE_SCHEMA,
    LockedInput,
    LockMismatch,
    read_lockfile_inputs,
    sha256_of,
)
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
from hydromodpy.data.registry.migrations import target_version as _cache_target_version

# The directory that holds the hydromodpy package, found from this module's
# dotted name so it stays right wherever the module sits. Its git commit is
# the HydroModPy commit a lockfile records.
_CHECKOUT_ROOT = Path(__file__).resolve().parents[__name__.count(".")]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _git_head(cwd: Path) -> str | None:
    import subprocess

    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return None
    return out.strip() or None


def _python_version() -> str:
    import sys

    info = sys.version_info
    return f"{info.major}.{info.minor}.{info.micro}"


def _solver_version_text(binary: Path) -> str | None:
    import subprocess

    if not binary.is_file() or not os.access(binary, os.X_OK):
        return None
    try:
        out = subprocess.check_output(
            [str(binary), "--version"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return out.strip() or None


def _entry_to_locked(
    row: dict[str, Any], *, catalog: DataCatalogDuckDB, fetched_at: str
) -> LockedInput | None:
    path = catalog.resolve_path(row["file_path"], variable=row.get("variable"))
    if not path.is_file():
        return None
    size: int | None = None
    try:
        size = path.stat().st_size
    except OSError:
        pass
    return LockedInput(
        variable=row["variable"],
        source=row["source"],
        station_id=row.get("station_id"),
        path=str(row["file_path"]),
        sha256=str(row.get("sha256") or sha256_of(path)),
        bytes=size,
        file_mtime=round(float(row["file_mtime"]), 6)
        if row.get("file_mtime") is not None
        else None,
        fetched_at=fetched_at,
    )


def _atomic_write_text(dest: Path, text: str) -> None:
    """Write *text* to *dest* atomically (tmp + fsync + replace)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.tmp.{uuid.uuid4().hex[:8]}"
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            os.write(fd, text.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, dest)
        try:
            dir_fd = os.open(str(dest.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # Directory fsync not supported (Windows/tmpfs); best-effort only.
            pass
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------- collect


def _collect_binaries(*, solvers: dict[str, Path] | None) -> dict[str, dict[str, str | None]]:
    """Compute SHA-256 + version text for every declared solver binary."""
    if not solvers:
        return {}
    payload: dict[str, dict[str, str | None]] = {}
    for name, path in solvers.items():
        p = Path(path) if path is not None else None
        if p is None or not p.is_file():
            payload[str(name)] = {"sha256": None, "version_text": None}
            continue
        payload[str(name)] = {
            "sha256": sha256_of(p),
            "version_text": _solver_version_text(p),
        }
    return payload


def _locked_inputs(catalog: DataCatalogDuckDB, *, fetched_at: str) -> list[LockedInput]:
    """Return one record per catalog entry whose file is on disk.

    ``fetched_at`` is read once per snapshot and stamped on every record,
    so one lockfile carries one instant instead of one clock read per row.
    """
    rows = catalog.backend.query(
        "SELECT variable, source, station_id, file_path, file_mtime, sha256 "
        "FROM entries ORDER BY variable, source, station_id, file_path"
    ).to_dict(orient="records")
    locked = (_entry_to_locked(row, catalog=catalog, fetched_at=fetched_at) for row in rows)
    return [item for item in locked if item is not None]


# ---------------------------------------------------------------------- public


def write_lockfile(
    catalog: DataCatalogDuckDB,
    dest: Path | str,
    *,
    schema_sha256: str | None = None,
    project_root: Path | str | None = None,
    solvers: dict[str, Path] | None = None,
    zarr_schema_version: str,
    parquet_schema_version: str,
) -> Path:
    """Freeze the current run environment + catalog inputs into ``dest``.

    The two storage schema versions belong to ``hydromodpy.results``, which this layer
    cannot import, so the caller passes them in.

    The file is written atomically (tmp + ``fsync`` + ``os.replace``). Its parts
    are always emitted:

    - ``schema``, the id of the format.
    - ``[hydromodpy]`` with version, git commit, python version, schema
      version numbers and the sha256 of the config schema.
    - ``[binaries]`` with per-solver ``sha256`` and ``version_text`` entries.
    - ``[[input]]``, one record per catalog entry whose file is on disk.
    """
    dest = Path(dest)

    # One snapshot, one instant: every timestamp in the file comes from here,
    # so a write that straddles a second boundary stays internally coherent.
    stamped_at = _now_iso()

    doc = tomlkit.document()
    doc.add("schema", LOCKFILE_SCHEMA)

    hmp_table = tomlkit.table()
    hmp_table.add("hydromodpy_version", _HMP_VERSION)
    git_commit = _git_head(_CHECKOUT_ROOT)
    if git_commit:
        hmp_table.add("git_commit", git_commit)
    project_commit = _git_head(Path(project_root)) if project_root else None
    if project_commit:
        hmp_table.add("project_git_commit", project_commit)
    hmp_table.add("python_version", _python_version())
    hmp_table.add("catalog_schema_version", _cache_target_version())
    hmp_table.add("zarr_schema_version", zarr_schema_version)
    hmp_table.add("parquet_schema_version", parquet_schema_version)
    if schema_sha256 is not None:
        hmp_table.add("config_schema_sha256", schema_sha256)
    hmp_table.add("generated_at", stamped_at)
    doc.add("hydromodpy", hmp_table)

    binaries_table = tomlkit.table()
    bin_payload = _collect_binaries(solvers=solvers)
    for solver_name, info in bin_payload.items():
        sha = info.get("sha256")
        ver = info.get("version_text")
        if sha is not None:
            binaries_table.add(f"{solver_name}_sha256", sha)
        if ver is not None:
            binaries_table.add(f"{solver_name}_version_text", ver)
    doc.add("binaries", binaries_table)

    records = tomlkit.aot()
    for item in _locked_inputs(catalog, fetched_at=stamped_at):
        table = tomlkit.table()
        table.add("variable", item.variable)
        table.add("source", item.source)
        if item.station_id is not None:
            table.add("station_id", item.station_id)
        table.add("path", item.path)
        table.add("sha256", item.sha256)
        if item.bytes is not None:
            table.add("bytes", item.bytes)
        if item.file_mtime is not None:
            table.add("file_mtime", item.file_mtime)
        table.add("fetched_at", item.fetched_at)
        records.append(table)
    doc["input"] = records

    _atomic_write_text(dest, tomlkit.dumps(doc))
    return dest


def verify_frozen(
    catalog: DataCatalogDuckDB,
    lockfile: Path | str,
) -> list[LockMismatch]:
    """Return every mismatch between the *lockfile* records and the catalog."""
    locked = {
        (item.variable, item.source, item.station_id, item.path): item
        for item in read_lockfile_inputs(lockfile)
    }
    mismatches: list[LockMismatch] = []
    rows = catalog.backend.fetch_all("SELECT variable, source, station_id, file_path FROM entries")
    seen = set()
    for variable, source, station_id, file_path in rows:
        key = (variable, source, station_id, file_path)
        seen.add(key)
        item = locked.get(key)
        p = catalog.resolve_path(file_path, variable=variable)
        if item is None:
            if not p.is_file():
                # A lock names files. An entry without one has nothing to verify.
                continue
            mismatches.append(
                LockMismatch(
                    kind="missing",
                    variable=variable,
                    source=source,
                    station_id=station_id,
                    expected=None,
                    observed=file_path,
                    path=str(file_path),
                )
            )
            continue
        if not p.is_file():
            mismatches.append(
                LockMismatch(
                    kind="missing",
                    variable=variable,
                    source=source,
                    station_id=station_id,
                    expected=item.sha256,
                    observed=None,
                    path=str(file_path),
                )
            )
            continue
        actual_sha = sha256_of(p)
        if actual_sha != item.sha256:
            mismatches.append(
                LockMismatch(
                    kind="sha256",
                    variable=variable,
                    source=source,
                    station_id=station_id,
                    expected=item.sha256,
                    observed=actual_sha,
                    path=str(file_path),
                )
            )
    for key, item in locked.items():
        if key not in seen:
            mismatches.append(
                LockMismatch(
                    kind="missing",
                    variable=item.variable,
                    source=item.source,
                    station_id=item.station_id,
                    expected=item.sha256,
                    observed=None,
                    path=item.path,
                )
            )
    return mismatches


def verify_inputs_strict(
    catalog: DataCatalogDuckDB,
    lockfile: Path | str,
) -> list[LockMismatch]:
    """Return what changed among the files the lockfile names, by path.

    Used by ``hmp dev lock verify --strict`` and ``hmp run --frozen`` to stop on a
    tracked input that changed. An entry the lockfile does not name is left to
    ``verify_frozen``, which also answers for a lockfile that names nothing.
    Missing artefacts are reported with ``kind="missing"``.
    """
    expected = {item.path: item for item in read_lockfile_inputs(lockfile)}
    if not expected:
        return verify_frozen(catalog, lockfile)
    rows = catalog.backend.fetch_all("SELECT variable, source, station_id, file_path FROM entries")
    mismatches: list[LockMismatch] = []
    for variable, source, station_id, file_path in rows:
        key = str(file_path)
        locked = expected.get(key)
        if locked is None:
            continue
        p = catalog.resolve_path(file_path, variable=variable)
        if not p.is_file():
            mismatches.append(
                LockMismatch(
                    kind="missing",
                    variable=variable,
                    source=source,
                    station_id=station_id,
                    expected=locked.sha256,
                    observed=None,
                    path=key,
                )
            )
            continue
        actual = sha256_of(p)
        if actual != locked.sha256:
            mismatches.append(
                LockMismatch(
                    kind="sha256",
                    variable=variable,
                    source=source,
                    station_id=station_id,
                    expected=locked.sha256,
                    observed=actual,
                    path=key,
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
    zarr_schema_version: str,
    parquet_schema_version: str,
    lockfile_dest: Path | str | None = None,
) -> Path:
    """Produce an archive containing the lockfile and every artefact."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    lockfile_dest = Path(lockfile_dest) if lockfile_dest else (dest.parent / LOCKFILE_NAME)
    write_lockfile(
        catalog,
        lockfile_dest,
        zarr_schema_version=zarr_schema_version,
        parquet_schema_version=parquet_schema_version,
    )

    stream, raw, mode = _open_writer(dest)
    try:
        with tarfile.open(fileobj=stream, mode=mode) as tar:
            tar.add(lockfile_dest, arcname=LOCKFILE_NAME)
            for fp, variable in catalog.backend.fetch_all(
                "SELECT file_path, variable FROM entries"
            ):
                p = catalog.resolve_path(fp, variable=variable)
                if p.is_file():
                    tar.add(p, arcname=f"artefacts/{sha256_of(p)}/{p.name}")
    finally:
        if hasattr(stream, "close"):
            stream.close()
        if raw is not None:
            raw.close()
    return dest


def restore_archive(archive: Path | str, dest_dir: Path | str) -> Path:
    """Extract *archive* into *dest_dir*, once every artefact its lockfile names is checked.

    The archive is read in a staging folder beside *dest_dir*, so a refused archive
    leaves nothing behind. An artefact that is absent or holds other bytes is refused,
    each one named.
    """
    archive = Path(archive)
    dest_dir = Path(dest_dir)
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{dest_dir.name}.restore.", dir=dest_dir.parent))
    try:
        stream, raw, mode = _open_reader(archive)
        try:
            with tarfile.open(fileobj=stream, mode=mode) as tar:
                tar.extractall(staging, filter="data")
        finally:
            if hasattr(stream, "close"):
                stream.close()
            if raw is not None:
                raw.close()
        _refuse_a_bad_archive(archive, staging)
        for path in sorted(staging.rglob("*")):
            target = dest_dir / path.relative_to(staging)
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(path, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return dest_dir


def _refuse_a_bad_archive(archive: Path, extracted: Path) -> None:
    """Refuse what was extracted when an artefact its lockfile names is absent or differs."""
    lockfile_path = extracted / LOCKFILE_NAME
    if not lockfile_path.is_file():
        raise CacheCorruptionError(
            f"{archive} holds no {LOCKFILE_NAME}, so nothing in it can be checked. "
            "Nothing was restored. Write it again with `hmp dev lock archive`."
        )
    faults: list[str] = []
    for item in read_lockfile_inputs(lockfile_path):
        candidate = extracted / "artefacts" / item.sha256 / Path(item.path).name
        if not candidate.is_file():
            faults.append(f"{item.path}: absent from the archive")
            continue
        actual = sha256_of(candidate)
        if actual != item.sha256:
            faults.append(f"{item.path}: expected sha256 {item.sha256}, got {actual}")
    if faults:
        raise CacheCorruptionError(
            f"{archive} does not hold what its {LOCKFILE_NAME} names, so nothing was restored. "
            "Write it again with `hmp dev lock archive`:\n  " + "\n  ".join(faults)
        )


__all__ = [
    "archive_lockfile",
    "restore_archive",
    "verify_frozen",
    "verify_inputs_strict",
    "write_lockfile",
]
