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
- ``verify_inputs_strict`` returns the same kind of report but is consumed by
  ``hmp dev lock verify --strict`` to map ``sha256`` mismatches to a non-zero
  exit.
"""

from __future__ import annotations

import os
import tarfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tomlkit

from hydromodpy.core.version import __version__ as _HMP_VERSION
from hydromodpy.data.provenance.lockfile import (
    LOCKFILE_NAME,
    LOCKFILE_VERSION,
    LockedArtifact,
    LockMismatch,
    read_lockfile,
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


# Schema versions tracked in the lockfile. The data layer cannot import from
# ``hydromodpy.results`` / ``hydromodpy.config`` (architecture matrix). The
# CLI (which spans every layer) injects fresh values via ``write_lockfile``
# parameters; these constants act as the safety fallback so the lockfile
# always carries a meaningful value.
ZARR_SCHEMA_VERSION_DEFAULT = "2"
PARQUET_SCHEMA_VERSION_DEFAULT = "v2"


def _entry_to_locked(
    row: dict[str, Any], *, catalog: DataCatalogDuckDB, fetched_at: str
) -> LockedArtifact | None:
    path = catalog.resolve_path(row["file_path"], variable=row.get("variable"))
    if not path.is_file():
        return None
    size: int | None = None
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
            payload[str(name)] = {"sha256": None, "version_text": None, "path": None}
            continue
        payload[str(name)] = {
            "sha256": sha256_of(p),
            "version_text": _solver_version_text(p),
            "path": str(p),
        }
    return payload


def _inputs_section(
    catalog: DataCatalogDuckDB,
    *,
    fetched_at: str,
) -> tuple[list[LockedArtifact], dict[str, dict[str, Any]]]:
    """Return (locked artefacts, inputs-by-path mapping).

    ``fetched_at`` is read once per snapshot and stamped on every artefact,
    so one lockfile carries one instant instead of one clock read per row.
    """
    rows = catalog.backend.query(
        "SELECT variable, source, station_id, file_path, file_mtime, sha256 "
        "FROM entries ORDER BY variable, source, station_id, file_path"
    ).to_dict(orient="records")
    locked: list[LockedArtifact] = []
    inputs: dict[str, dict[str, Any]] = {}
    for row in rows:
        la = _entry_to_locked(row, catalog=catalog, fetched_at=fetched_at)
        if la is None:
            continue
        locked.append(la)
        key = str(row["file_path"])
        inputs[key] = {
            "sha256": la.sha256,
            "bytes": int(la.size_bytes) if la.size_bytes is not None else 0,
            "fetched_at": la.fetched_at,
        }
    return locked, inputs


# ---------------------------------------------------------------------- public


def write_lockfile(
    catalog: DataCatalogDuckDB,
    dest: Path | str,
    *,
    schema_sha256: str | None = None,
    project_root: Path | str | None = None,
    solvers: dict[str, Path] | None = None,
    zarr_schema_version: str | None = None,
    parquet_schema_version: str | None = None,
) -> Path:
    """Freeze the current run environment + catalog inputs into ``dest``.

    The file is written atomically (tmp + ``fsync`` + ``os.replace``). The
    four mandatory sections are always emitted:

    - ``[hydromodpy]`` with version, git commit, python version, schema
      version numbers.
    - ``[binaries]`` with per-solver ``sha256`` and ``version_text`` entries.
    - ``[schema]`` summary of catalog / zarr / parquet schema versions.
    - ``[inputs]`` keyed by relative path with ``sha256`` / ``bytes`` /
      ``fetched_at``.

    Existing ``[[artefact]]`` records remain so legacy frozen-mode replay
    keeps working.
    """
    dest = Path(dest)

    zarr_ver = zarr_schema_version or ZARR_SCHEMA_VERSION_DEFAULT
    parquet_ver = parquet_schema_version or PARQUET_SCHEMA_VERSION_DEFAULT
    # One snapshot, one instant: every timestamp in the file comes from here,
    # so a write that straddles a second boundary stays internally coherent.
    stamped_at = _now_iso()

    doc = tomlkit.document()

    hmp_table = tomlkit.table()
    hmp_table.add("version", LOCKFILE_VERSION)
    hmp_table.add("hydromodpy_version", _HMP_VERSION)
    git_commit = _git_head(_CHECKOUT_ROOT)
    if git_commit:
        hmp_table.add("git_commit", git_commit)
    project_commit = _git_head(Path(project_root)) if project_root else None
    if project_commit:
        hmp_table.add("project_git_commit", project_commit)
    hmp_table.add("python_version", _python_version())
    hmp_table.add("catalog_schema_version", _cache_target_version())
    hmp_table.add("zarr_schema_version", zarr_ver)
    hmp_table.add("parquet_schema_version", parquet_ver)
    hmp_table.add("generated_at", stamped_at)
    doc.add("hydromodpy", hmp_table)

    binaries_table = tomlkit.table()
    bin_payload = _collect_binaries(solvers=solvers)
    for solver_name, info in bin_payload.items():
        sha = info.get("sha256")
        ver = info.get("version_text")
        path = info.get("path")
        if sha is not None:
            binaries_table.add(f"{solver_name}_sha256", sha)
        if ver is not None:
            binaries_table.add(f"{solver_name}_version_text", ver)
        if path is not None:
            binaries_table.add(f"{solver_name}_path", path)
    doc.add("binaries", binaries_table)

    schema_table = tomlkit.table()
    schema_table.add("catalog", _cache_target_version())
    schema_table.add("zarr", zarr_ver)
    schema_table.add("parquet", parquet_ver)
    if schema_sha256 is not None:
        schema_table.add("config_sha256", schema_sha256)
    doc.add("schema", schema_table)

    locked_list, inputs_payload = _inputs_section(catalog, fetched_at=stamped_at)

    inputs_table = tomlkit.table()
    for rel_path, payload in inputs_payload.items():
        inline = tomlkit.inline_table()
        inline["sha256"] = payload["sha256"]
        inline["bytes"] = int(payload["bytes"])
        inline["fetched_at"] = payload["fetched_at"]
        inputs_table.add(rel_path, inline)
    doc.add("inputs", inputs_table)

    artefacts = tomlkit.aot()
    for la in locked_list:
        table = tomlkit.table()
        table.add("variable", la.variable)
        table.add("source", la.source)
        if la.station_id is not None:
            table.add("station_id", la.station_id)
        table.add("file_path", la.file_path)
        table.add("sha256", la.sha256)
        if la.file_mtime is not None:
            table.add("file_mtime", la.file_mtime)
        if la.size_bytes is not None:
            table.add("size_bytes", la.size_bytes)
        table.add("fetched_at", la.fetched_at)
        artefacts.append(table)
    doc["artefact"] = artefacts

    _atomic_write_text(dest, tomlkit.dumps(doc))
    return dest


def verify_frozen(
    catalog: DataCatalogDuckDB,
    lockfile: Path | str,
) -> list[LockMismatch]:
    """Return every mismatch between *lockfile* artefacts and the catalog."""
    locked = {
        (la.variable, la.source, la.station_id, la.file_path): la for la in read_lockfile(lockfile)
    }
    mismatches: list[LockMismatch] = []
    rows = catalog.backend.fetch_all("SELECT variable, source, station_id, file_path FROM entries")
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
                    path=str(file_path),
                )
            )
            continue
        p = catalog.resolve_path(file_path, variable=variable)
        if not p.is_file():
            mismatches.append(
                LockMismatch(
                    kind="missing",
                    variable=variable,
                    source=source,
                    station_id=station_id,
                    expected=la.sha256,
                    observed=None,
                    path=str(file_path),
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
                    path=str(file_path),
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
                    path=la.file_path,
                )
            )
    return mismatches


def verify_inputs_strict(
    catalog: DataCatalogDuckDB,
    lockfile: Path | str,
) -> list[LockMismatch]:
    """Return only ``sha256`` mismatches found in the ``[inputs]`` section.

    Used by ``hmp dev lock verify --strict`` to fail with exit 1 when any tracked
    input changed. Missing artefacts are reported with ``kind="missing"``.
    """
    expected = read_lockfile_inputs(lockfile)
    if not expected:
        return verify_frozen(catalog, lockfile)
    rows = catalog.backend.fetch_all("SELECT variable, source, station_id, file_path FROM entries")
    mismatches: list[LockMismatch] = []
    for variable, source, station_id, file_path in rows:
        key = str(file_path)
        meta = expected.get(key)
        if meta is None:
            continue
        p = catalog.resolve_path(file_path, variable=variable)
        if not p.is_file():
            mismatches.append(
                LockMismatch(
                    kind="missing",
                    variable=variable,
                    source=source,
                    station_id=station_id,
                    expected=meta["sha256"],
                    observed=None,
                    path=key,
                )
            )
            continue
        actual = sha256_of(p)
        if actual != meta["sha256"]:
            mismatches.append(
                LockMismatch(
                    kind="sha256",
                    variable=variable,
                    source=source,
                    station_id=station_id,
                    expected=meta["sha256"],
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
    "archive_lockfile",
    "restore_archive",
    "verify_frozen",
    "verify_inputs_strict",
    "write_lockfile",
]
