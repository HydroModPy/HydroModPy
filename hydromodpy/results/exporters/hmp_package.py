"""Portable ``.hmp`` package export / import (tar.zst + SHA-256 manifest).

A ``.hmp`` file is a single ``tar`` archive compressed with Zstandard,
containing:

* ``manifest.json`` — archive header with the HydroModPy version that
  produced the archive, the simulation UUID, and a list of
  ``{path, size, sha256}`` entries covering every other file. The manifest is
  itself included in the archive under ``manifest.json`` (its own sha256 is
  therefore omitted — checksums are verified against the other files).
* ``catalog_snapshot.duckdb`` — a one-simulation DuckDB snapshot containing
  the ``simulations`` row plus per-sim data (parameters, timeseries,
  budgets, metrics, provenance, geographic features / metadata, tags,
  runs_environment).
* ``simulation.zarr.zip`` — the simulation's Zarr store, packed to a
  deterministic ``zip`` file (already BLOSC-compressed internally).
* ``geographic/`` (optional) — the workspace-level content-addressable
  raster cache materialised for the simulation's ``geographic_fingerprint``,
  so the archive is self-contained on a fresh workspace.
* ``README.md`` — human-readable summary generated at export time.

The archive is *reproducible*: given the same inputs, the archive layout,
file ordering and manifest are byte-identical, which makes SHA-256 checks
meaningful for tamper detection.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import shutil
import tarfile
import tempfile
import zipfile
from importlib import metadata as _importlib_metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.results.geographic_cache import (
    CACHE_DIRNAME,
    MANIFEST_FILENAME,
    GeographicCache,
)

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
README_NAME = "README.md"
CATALOG_SNAPSHOT_NAME = "catalog_snapshot.duckdb"
ZARR_ARCHIVE_NAME = "simulation.zarr.zip"
GEOGRAPHIC_SUBDIR = "geographic"
HMP_FORMAT_VERSION = "1.0"
HMP_MAGIC = "hydromodpy/hmp"


def _hydromodpy_version() -> str:
    try:
        return _importlib_metadata.version("hydromodpy")
    except _importlib_metadata.PackageNotFoundError:
        return "unknown"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_package_files(staging: Path) -> list[Path]:
    """Sorted list of files that belong in the archive (manifest excluded)."""
    files: list[Path] = []
    for path in sorted(staging.rglob("*")):
        if not path.is_file():
            continue
        if path.name == MANIFEST_NAME and path.parent == staging:
            continue  # manifest is the last entry, assembled separately
        files.append(path)
    return files


def _pack_zarr(zarr_src: Path, dst: Path) -> None:
    """Pack a zarr directory (or copy an already-zipped zarr) to ``dst``."""
    if zarr_src.is_file():
        shutil.copy2(zarr_src, dst)
        return
    if not zarr_src.is_dir():
        raise FileNotFoundError(f"Zarr store not found at {zarr_src}")
    with zipfile.ZipFile(str(dst), "w", compression=zipfile.ZIP_STORED) as zf:
        for fpath in sorted(zarr_src.rglob("*")):
            if fpath.is_file():
                zf.write(str(fpath), str(fpath.relative_to(zarr_src)))


def _materialise_geographic(
    workspace_path: Path, fingerprint: str | None, staging: Path,
) -> None:
    if not fingerprint:
        return
    cache = GeographicCache(workspace_path)
    if not cache.is_cached(fingerprint):
        logger.warning(
            "Geographic fingerprint %s not found in cache %s — archive will "
            "ship without geographic payload",
            fingerprint, cache.root,
        )
        return
    dst = staging / GEOGRAPHIC_SUBDIR
    dst.mkdir(parents=True, exist_ok=True)
    src = cache.load(fingerprint)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def _dematerialise_geographic(
    staging: Path, workspace_path: Path, fingerprint: str | None,
    *, overwrite: bool = False,
) -> None:
    src = staging / GEOGRAPHIC_SUBDIR
    if not src.is_dir():
        return
    if fingerprint is None:
        manifest_path = src / MANIFEST_FILENAME
        if manifest_path.is_file():
            try:
                fingerprint = json.loads(manifest_path.read_text()).get(
                    "fingerprint"
                )
            except (json.JSONDecodeError, OSError):
                fingerprint = None
    if not fingerprint:
        logger.warning("No fingerprint for geographic payload — skipping cache")
        return
    manifest = {}
    mpath = src / MANIFEST_FILENAME
    if mpath.is_file():
        try:
            data = json.loads(mpath.read_text())
            manifest = data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            manifest = {}
    GeographicCache(workspace_path).save(
        fingerprint, src, manifest=manifest, overwrite=overwrite,
    )


def _dump_catalog_snapshot(
    conn: "duckdb.DuckDBPyConnection", sim_id: str, dst: Path,
) -> None:
    """Create a one-sim DuckDB snapshot at ``dst``."""
    import duckdb as _duckdb

    from hydromodpy.results.catalog_schema import (
        PER_SIM_TABLE_NAMES,
        ensure_schema,
    )

    if dst.exists():
        dst.unlink()
    snap = _duckdb.connect(str(dst))
    try:
        ensure_schema(snap)
        sim_df = conn.execute(
            "SELECT * FROM simulations WHERE sim_id = ?", [sim_id],
        ).fetchdf()
        if sim_df.empty:
            raise KeyError(f"Simulation '{sim_id}' not found")
        snap.execute("INSERT INTO simulations SELECT * FROM sim_df")

        for table in PER_SIM_TABLE_NAMES:
            df = conn.execute(
                f"SELECT * FROM {table} WHERE sim_id = ?", [sim_id],
            ).fetchdf()
            if df.empty:
                continue
            snap.execute(f"INSERT INTO {table} SELECT * FROM df")
    finally:
        snap.close()


def _restore_catalog_snapshot(
    conn: "duckdb.DuckDBPyConnection", snapshot_path: Path,
) -> str:
    """Import the rows from ``snapshot_path`` into the open catalog.

    Returns the imported ``sim_id``.
    """
    import duckdb as _duckdb

    from hydromodpy.results.catalog_schema import PER_SIM_TABLE_NAMES

    snap = _duckdb.connect(str(snapshot_path), read_only=True)
    try:
        sim_row = snap.execute("SELECT sim_id FROM simulations").fetchone()
        if sim_row is None:
            raise ValueError("Snapshot contains no simulation row")
        sid = str(sim_row[0])

        pkg_tables = {
            r[0] for r in snap.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='main' AND table_type='BASE TABLE'"
            ).fetchall()
        }

        sim_df = snap.execute("SELECT * FROM simulations").fetchdf()
        conn.execute("INSERT INTO simulations SELECT * FROM sim_df")

        for table in PER_SIM_TABLE_NAMES:
            if table not in pkg_tables:
                continue
            df = snap.execute(f"SELECT * FROM {table}").fetchdf()
            if df.empty:
                continue
            conn.execute(f"INSERT INTO {table} SELECT * FROM df")
    finally:
        snap.close()

    return sid


def _build_manifest(
    sim_id: str, staging: Path, geographic_fingerprint: str | None,
) -> dict[str, Any]:
    files = []
    for path in _iter_package_files(staging):
        files.append(
            {
                "path": str(path.relative_to(staging)).replace("\\", "/"),
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return {
        "format": HMP_MAGIC,
        "format_version": HMP_FORMAT_VERSION,
        "sim_id": sim_id,
        "hydromodpy_version": _hydromodpy_version(),
        "geographic_fingerprint": geographic_fingerprint,
        "files": files,
    }


def _write_readme(sim_id: str, dst: Path) -> None:
    dst.write_text(
        (
            f"# HydroModPy simulation package\n\n"
            f"- **sim_id**: `{sim_id}`\n"
            f"- **format_version**: `{HMP_FORMAT_VERSION}`\n"
            f"- **hydromodpy_version**: `{_hydromodpy_version()}`\n\n"
            "Import with `SimulationCatalog.import_package(<path>.hmp)`.\n"
            "Integrity of the archive is verified against `manifest.json` "
            "on import (SHA-256 per file).\n"
        ),
        encoding="utf-8",
    )


def _write_tar_zst(staging: Path, output: Path) -> None:
    """Pack ``staging`` (with a manifest at its root) into ``output`` (tar.zst).

    File order is deterministic (sorted) so the archive is reproducible.
    """
    import zstandard as zstd

    files = sorted(staging.rglob("*"))
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for path in files:
            if not path.is_file():
                continue
            arcname = str(path.relative_to(staging)).replace("\\", "/")
            info = tar.gettarinfo(str(path), arcname=arcname)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            with open(path, "rb") as fh:
                tar.addfile(info, fh)
    cctx = zstd.ZstdCompressor(level=10)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "wb") as fh:
        fh.write(cctx.compress(buffer.getvalue()))


def _read_tar_zst(archive: Path, staging: Path) -> None:
    """Extract ``archive`` (tar.zst) into ``staging``."""
    import zstandard as zstd

    dctx = zstd.ZstdDecompressor()
    with open(archive, "rb") as fh:
        raw = dctx.decompress(fh.read())
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r") as tar:
        tar.extractall(str(staging), filter="data")


def export_hmp_package(
    catalog: Any,
    sim_id: str,
    output_path: Path | str,
) -> Path:
    """Export a single simulation as a portable ``.hmp`` archive (tar.zst).

    Parameters
    ----------
    catalog
        The source :class:`SimulationCatalog` instance (passed as ``Any`` to
        avoid a circular import).
    sim_id
        The simulation UUID to export.
    output_path
        Destination file path. The ``.hmp`` suffix is added when missing.
    """
    sid = str(sim_id)
    output = Path(output_path)
    if output.suffix != ".hmp":
        output = output.with_suffix(output.suffix + ".hmp") \
            if output.suffix else output.with_suffix(".hmp")

    row = catalog.connection.execute(
        "SELECT zarr_path, geographic_fingerprint FROM simulations "
        "WHERE sim_id = ?", [sid],
    ).fetchone()
    if row is None:
        raise KeyError(f"Simulation '{sid}' not found")
    zarr_rel, geo_fp = row
    workspace = catalog.workspace_path
    zarr_src = workspace / zarr_rel

    with tempfile.TemporaryDirectory(prefix="hmp_export_") as tmpdir:
        staging = Path(tmpdir) / sid
        staging.mkdir()

        _dump_catalog_snapshot(
            catalog.connection, sid, staging / CATALOG_SNAPSHOT_NAME,
        )
        _pack_zarr(zarr_src, staging / ZARR_ARCHIVE_NAME)
        _materialise_geographic(workspace, geo_fp, staging)
        _write_readme(sid, staging / README_NAME)

        manifest = _build_manifest(sid, staging, geo_fp)
        (staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        # Root the archive at the sim_id directory so consumers can see a
        # single top-level folder.
        _write_tar_zst(staging.parent, output)

    logger.info("Exported simulation %s to %s", sid, output)
    return output


def import_hmp_package(
    catalog: Any,
    package_path: Path | str,
    *,
    force: bool = False,
) -> str:
    """Import a ``.hmp`` archive into the given catalog's workspace.

    Verifies that every file listed in ``manifest.json`` is present with a
    matching SHA-256 before any catalog mutation. Returns the imported
    ``sim_id``.
    """
    import duckdb as _duckdb

    archive = Path(package_path)
    if not archive.is_file():
        raise FileNotFoundError(f"No .hmp archive at {archive}")

    with tempfile.TemporaryDirectory(prefix="hmp_import_") as tmpdir:
        staging = Path(tmpdir)
        _read_tar_zst(archive, staging)

        # The archive has a single sim_id directory at its root
        roots = [p for p in staging.iterdir() if p.is_dir()]
        if len(roots) != 1:
            raise ValueError(
                f"Expected exactly one top-level directory in archive, "
                f"found {len(roots)}"
            )
        pkg = roots[0]

        manifest_path = pkg / MANIFEST_NAME
        if not manifest_path.is_file():
            raise ValueError(f"{MANIFEST_NAME} is missing from the archive")
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("format") != HMP_MAGIC:
            raise ValueError(
                f"Unexpected archive format: {manifest.get('format')!r}"
            )
        sid = str(manifest["sim_id"])

        for entry in manifest["files"]:
            path = pkg / entry["path"]
            if not path.is_file():
                raise ValueError(
                    f"Archive is missing file listed in manifest: {entry['path']}"
                )
            actual = _sha256_file(path)
            if actual != entry["sha256"]:
                raise ValueError(
                    f"SHA-256 mismatch for {entry['path']}: "
                    f"expected {entry['sha256']}, got {actual}"
                )

        existing = catalog.connection.execute(
            "SELECT sim_id FROM simulations WHERE sim_id = ?", [sid],
        ).fetchone()
        if existing is not None:
            if not force:
                raise ValueError(
                    f"Simulation '{sid}' already exists. "
                    "Use force=True to overwrite."
                )
            catalog.delete(sid)

        snap_path = pkg / CATALOG_SNAPSHOT_NAME
        if not snap_path.is_file():
            raise ValueError(f"{CATALOG_SNAPSHOT_NAME} missing from archive")

        catalog.connection.begin()
        try:
            _restore_catalog_snapshot(catalog.connection, snap_path)
            workspace = catalog.workspace_path
            zarr_path = f"simulations/{sid}.zarr.zip"
            catalog.connection.execute(
                "UPDATE simulations SET zarr_path = ? WHERE sim_id = ?",
                [zarr_path, sid],
            )
            catalog.connection.commit()
        except Exception:
            catalog.connection.rollback()
            raise

        dst = workspace / zarr_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pkg / ZARR_ARCHIVE_NAME, dst)

        _dematerialise_geographic(
            pkg, workspace, manifest.get("geographic_fingerprint"),
            overwrite=force,
        )

    logger.info("Imported simulation %s from %s", sid, archive)
    return sid


# Kept for backwards compatibility inside the same module, no longer used
# from the catalog.
def materialize_geographic_on_export(
    workspace_path: Path | str,
    fingerprint: str | None,
    package_dir: Path | str,
) -> Path | None:
    """Deprecated helper from the pre-G05 folder-based ``.hmp``.

    Left as a thin wrapper so scripts that imported the helper directly keep
    working while the rest of the system migrates to
    :func:`export_hmp_package`.
    """
    pkg = Path(package_dir)
    pkg.mkdir(parents=True, exist_ok=True)
    _materialise_geographic(Path(workspace_path), fingerprint, pkg)
    return pkg / GEOGRAPHIC_SUBDIR if (pkg / GEOGRAPHIC_SUBDIR).is_dir() else None


def dematerialize_geographic_on_import(
    package_dir: Path | str,
    workspace_path: Path | str,
    fingerprint: str | None = None,
    *,
    overwrite: bool = False,
) -> str | None:
    """Deprecated helper from the pre-G05 folder-based ``.hmp``."""
    pkg = Path(package_dir)
    _dematerialise_geographic(
        pkg, Path(workspace_path), fingerprint, overwrite=overwrite,
    )
    return fingerprint


__all__ = [
    "CACHE_DIRNAME",
    "GEOGRAPHIC_SUBDIR",
    "HMP_FORMAT_VERSION",
    "HMP_MAGIC",
    "MANIFEST_NAME",
    "export_hmp_package",
    "import_hmp_package",
    "materialize_geographic_on_export",
    "dematerialize_geographic_on_import",
]
