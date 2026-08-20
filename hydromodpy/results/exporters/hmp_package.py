"""Portable ``.hmp`` package export / import (tar.zst + SHA-256 manifest).

A ``.hmp`` file is a single ``tar`` archive compressed with Zstandard,
containing:

* ``manifest.json`` - archive header with the HydroModPy version that
  produced the archive, the simulation UUID, and a list of
  ``{path, size, sha256}`` entries covering every other file. The manifest is
  itself included in the archive under ``manifest.json`` (its own sha256 is
  therefore omitted - checksums are verified against the other files).
* ``catalog_snapshot.duckdb`` - a one-simulation DuckDB snapshot containing
  the ``simulations`` row plus per-sim data (parameters, timeseries,
  budgets, metrics, provenance, geographic features / metadata, tags,
  runs_environment).
* ``fields.zarr.zip`` - the run's Zarr store, packed to a deterministic
  ``zip`` file (already BLOSC-compressed internally) so the manifest keeps
  one checksum for the whole store. Import unpacks it back to the directory
  store at ``runs/<name>/fields.zarr``; nothing on disk stays zipped.
* ``run/`` - the seal of the run directory (``manifest.json``,
  ``provenance.json``, frozen ``config.toml``), copied verbatim. The archive
  is therefore built on a *sealed* run: packing before the seal would ship a
  run nobody can read back without an index. It lives in a sub-directory
  because the archive root already owns a ``manifest.json`` of its own.
* ``geographic/`` (optional) - the workspace-level content-addressable
  raster cache materialised for the simulation's ``geographic_fingerprint``,
  so the archive is self-contained on a fresh workspace.
* ``README.md`` - human-readable summary generated at export time.

The archive is *reproducible*: given the same inputs, the archive layout,
file ordering and manifest are byte-identical, which makes SHA-256 checks
meaningful for tamper detection.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
import zipfile
from importlib import metadata as _importlib_metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import RUNS_DIRNAME, decode_workspace_path
from hydromodpy.results.geographic_cache import (
    CACHE_DIRNAME,
    MANIFEST_FILENAME,
    GeographicCache,
)
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    RUN_CONFIG_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_PROVENANCE_FILENAME,
)

if TYPE_CHECKING:
    import duckdb

logger = get_logger(__name__)

MANIFEST_NAME = "manifest.json"
README_NAME = "README.md"
CATALOG_SNAPSHOT_NAME = "catalog_snapshot.duckdb"
ZARR_ARCHIVE_NAME = "fields.zarr.zip"
GEOGRAPHIC_SUBDIR = "geographic"
INPUTS_SUBDIR = "inputs"
INPUTS_MANIFEST_NAME = "manifest.json"
PARQUET_SUBDIR = "parquet"
RUN_SEAL_SUBDIR = "run"
RUN_SEAL_FILENAMES: tuple[str, ...] = (
    RUN_MANIFEST_FILENAME,
    RUN_PROVENANCE_FILENAME,
    RUN_CONFIG_FILENAME,
)
RO_CRATE_METADATA_NAME = "ro-crate-metadata.json"
HMP_FORMAT_VERSION = "1.4"
HMP_MAGIC = "hydromodpy/hmp"
SHAPEFILE_SIDECAR_EXTS = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx")


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


def _materialise_parquet(
    src_dir: Path,
    staging: Path,
) -> list[str]:
    """Copy the run's Parquet payloads into the archive staging area.

    Every ``.parquet`` file of the run travels, not only the DuckDB-backed
    views: ``parameters`` and ``simulation`` are written by the seal and are
    exactly what a disk-only rebuild reads back, so an archive without them
    would import a run that cannot be re-indexed.

    Returns the list of file base names that were bundled (empty when the
    simulation was registered but never had any per-sim rows, e.g. an
    overview-only run).
    """
    if not src_dir.is_dir():
        return []
    dst_dir = staging / PARQUET_SUBDIR
    copied: list[str] = []
    for src in sorted(src_dir.glob(f"*{PARQUET_FILE_SUFFIX}")):
        if not src.is_file():
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst_dir / src.name)
        copied.append(src.name)
    return copied


def _materialise_run_seal(run_dir: Path, staging: Path) -> list[str]:
    """Copy the run seal into ``run/`` inside the archive.

    The seal is what makes a run directory readable without the index:
    ``manifest.json``, ``provenance.json`` and the frozen ``config.toml``.
    They travel in a sub-directory because the archive root already owns a
    ``manifest.json`` of its own (the checksum header). Returns the file
    names that were bundled; empty when the run was never sealed.
    """
    if not run_dir.is_dir():
        return []
    dst_dir = staging / RUN_SEAL_SUBDIR
    copied: list[str] = []
    for name in RUN_SEAL_FILENAMES:
        src = run_dir / name
        if not src.is_file():
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst_dir / name)
        copied.append(name)
    return copied


def _dematerialise_run_seal(pkg: Path, run_dir: Path) -> list[str]:
    """Restore the run seal from the archive into the run directory."""
    src_dir = pkg / RUN_SEAL_SUBDIR
    if not src_dir.is_dir():
        return []
    run_dir.mkdir(parents=True, exist_ok=True)
    restored: list[str] = []
    for name in RUN_SEAL_FILENAMES:
        src = src_dir / name
        if not src.is_file():
            continue
        shutil.copy2(src, run_dir / name)
        restored.append(name)
    return restored


def _dematerialise_parquet(
    pkg: Path,
    dst_dir: Path,
) -> list[str]:
    """Copy Parquet files from the archive into the workspace layout.

    Returns the list of file base names that were materialised.
    """
    src_dir = pkg / PARQUET_SUBDIR
    if not src_dir.is_dir():
        return []
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for src in sorted(src_dir.iterdir()):
        # Single-file Parquet payloads only; an entry sharing the suffix could
        # be a directory (e.g. future partitioned dataset) which is not handled
        # by this importer.
        if not src.is_file() or src.suffix != PARQUET_FILE_SUFFIX:
            continue
        shutil.copy2(src, dst_dir / src.name)
        copied.append(src.name)
    return copied


# Earliest timestamp the ZIP format can store. Stamped on every member so two
# exports of the same store produce byte-identical zarr.zip bytes (the tar layer
# normalizes mtime to 0; ZIP cannot go below 1980).
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def _unpack_zarr(archive: Path, dst: Path) -> None:
    """Extract a packed Zarr archive into the run's ``fields.zarr`` directory."""
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    with zipfile.ZipFile(str(archive), "r") as zf:
        zf.extractall(str(dst))


def _pack_zarr(zarr_src: Path, dst: Path) -> None:
    """Pack the run's ``fields.zarr`` directory into ``dst``.

    Member timestamps and permissions are normalized so the archive is
    reproducible: the on-disk mtime is not stamped into the ZIP.
    """
    if not zarr_src.is_dir():
        raise FileNotFoundError(f"Zarr store not found at {zarr_src}")
    with zipfile.ZipFile(str(dst), "w", compression=zipfile.ZIP_STORED) as zf:
        for fpath in sorted(zarr_src.rglob("*")):
            if not fpath.is_file():
                continue
            arcname = str(fpath.relative_to(zarr_src)).replace("\\", "/")
            info = zipfile.ZipInfo(arcname, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            zf.writestr(info, fpath.read_bytes())


def _looks_like_shapefile(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".shp"


def _bundle_shapefile(path: Path, dst_dir: Path, basename_prefix: str) -> str:
    """Pack a .shp and its sidecars into one .shp.zip and return archive path."""
    stem = path.stem
    parent = path.parent
    archive_name = f"{basename_prefix}{path.name}.zip"
    archive_path = dst_dir / archive_name
    with zipfile.ZipFile(str(archive_path), "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for ext in SHAPEFILE_SIDECAR_EXTS:
            sidecar = parent / f"{stem}{ext}"
            if sidecar.is_file():
                zf.write(str(sidecar), sidecar.name)
    return archive_name


def _copy_directory_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst)


def _bundle_one_input(
    entry_row: dict,
    staging_inputs: Path,
    workspace_path: Path,
) -> dict | None:
    """Copy or pack one tracked file into the inputs staging area.

    Returns the manifest entry for this file, or ``None`` if the source is
    missing on disk at export time.
    """
    src = decode_workspace_path(workspace_path, str(entry_row["canonical_path"]))
    if not src.exists():
        logger.warning(
            "Tracked file missing at export time, skipping: %s",
            src,
        )
        return None

    role = str(entry_row["role"])
    sha12 = str(entry_row["sha256"])[:12]
    role_dir = staging_inputs / role
    role_dir.mkdir(parents=True, exist_ok=True)

    if src.is_dir():
        dst_dir = role_dir / f"{sha12}__{src.name}"
        _copy_directory_tree(src, dst_dir)
        archive_rel = f"{INPUTS_SUBDIR}/{role}/{sha12}__{src.name}"
        is_directory = True
    elif _looks_like_shapefile(src):
        arc_name = _bundle_shapefile(src, role_dir, f"{sha12}__")
        archive_rel = f"{INPUTS_SUBDIR}/{role}/{arc_name}"
        is_directory = False
    else:
        dst_name = f"{sha12}__{src.name}"
        shutil.copy2(src, role_dir / dst_name)
        archive_rel = f"{INPUTS_SUBDIR}/{role}/{dst_name}"
        is_directory = False

    return {
        "role": role,
        "category": str(entry_row["category"]),
        "original_path": str(entry_row["original_path"]),
        "archive_path": archive_rel,
        "sha256": str(entry_row["sha256"]),
        "size_bytes": int(entry_row["size_bytes"]),
        "is_directory": is_directory,
    }


def _materialise_inputs(
    catalog: Any,
    sim_id: str,
    staging: Path,
) -> list[dict]:
    """Copy every tracked input for ``sim_id`` into ``staging/inputs/``.

    Writes ``inputs/manifest.json`` listing each bundled input. Returns
    the manifest list (also useful for the root manifest).
    """
    rows = catalog.backend.query(
        """SELECT role, category, original_path, canonical_path,
                  sha256, size_bytes, portable
           FROM tracked_files WHERE sim_id = ?
           ORDER BY role, canonical_path""",
        [sim_id],
    )
    if rows.empty:
        return []

    staging_inputs = staging / INPUTS_SUBDIR
    staging_inputs.mkdir(parents=True, exist_ok=True)

    entries: list[dict] = []
    for _, row in rows.iterrows():
        if not bool(row["portable"]):
            continue
        bundled = _bundle_one_input(dict(row), staging_inputs, catalog.workspace_path)
        if bundled is not None:
            entries.append(bundled)

    (staging_inputs / INPUTS_MANIFEST_NAME).write_text(
        json.dumps(entries, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return entries


def _materialise_geographic(
    workspace_path: Path,
    fingerprint: str | None,
    staging: Path,
) -> None:
    if not fingerprint:
        return
    cache = GeographicCache(workspace_path)
    if not cache.is_cached(fingerprint):
        logger.warning(
            "Geographic fingerprint %s not found in cache %s - archive will "
            "ship without geographic payload",
            fingerprint,
            cache.root,
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
    staging: Path,
    workspace_path: Path,
    fingerprint: str | None,
    *,
    overwrite: bool = False,
) -> None:
    src = staging / GEOGRAPHIC_SUBDIR
    if not src.is_dir():
        return
    if fingerprint is None:
        manifest_path = src / MANIFEST_FILENAME
        if manifest_path.is_file():
            try:
                fingerprint = json.loads(manifest_path.read_text()).get("fingerprint")
            except (json.JSONDecodeError, OSError):
                fingerprint = None
    if not fingerprint:
        logger.warning("No fingerprint for geographic payload - skipping cache")
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
        fingerprint,
        src,
        manifest=manifest,
        overwrite=overwrite,
    )


def _dump_catalog_snapshot(
    conn: duckdb.DuckDBPyConnection,
    sim_id: str,
    dst: Path,
) -> None:
    """Create a one-sim DuckDB snapshot at ``dst``."""
    import duckdb as _duckdb

    from hydromodpy.results.catalog.adapters.duckdb import DuckDBBackend
    from hydromodpy.results.catalog.constants import PER_SIM_TABLE_NAMES
    from hydromodpy.results.catalog.migrations import ensure_schema

    if dst.exists():
        dst.unlink()
    snap = _duckdb.connect(str(dst))
    try:
        ensure_schema(snap)
        src_backend = DuckDBBackend.from_connection(conn)
        sim_df = src_backend.query(
            "SELECT * FROM simulations WHERE sim_id = ?",
            [sim_id],
        )
        if sim_df.empty:
            raise KeyError(f"Simulation '{sim_id}' not found")
        # DuckDB replacement scan needs the local sim_df symbol below.
        snap.execute("INSERT INTO simulations SELECT * FROM sim_df")

        for table in PER_SIM_TABLE_NAMES:
            df = src_backend.query(
                f"SELECT * FROM {table} WHERE sim_id = ?",
                [sim_id],
            )
            if df.empty:
                continue
            snap.execute(f"INSERT INTO {table} SELECT * FROM df")
    finally:
        snap.close()
        # The migration lock lands in the staging tree the manifest and the tar
        # rglob, and POSIX keeps it where Windows unlinks it: leaving it makes
        # the archive differ across platforms.
        for suffix in (".wal", ".lock"):
            dst.with_name(f"{dst.name}{suffix}").unlink(missing_ok=True)


def _restore_catalog_snapshot(
    conn: duckdb.DuckDBPyConnection,
    snapshot_path: Path,
) -> str:
    """Import the rows from ``snapshot_path`` into the open catalog.

    Returns the imported ``sim_id``.
    """
    import duckdb as _duckdb

    from hydromodpy.results.catalog.constants import PER_SIM_TABLE_NAMES

    snap = _duckdb.connect(str(snapshot_path), read_only=True)
    try:
        from hydromodpy.results.catalog.adapters.duckdb import DuckDBBackend

        snap_backend = DuckDBBackend.from_connection(snap)
        sim_row = snap_backend.fetch_one("SELECT sim_id FROM simulations")
        if sim_row is None:
            raise ValueError("Snapshot contains no simulation row")
        sid = str(sim_row[0])

        pkg_tables = {
            r[0]
            for r in snap_backend.fetch_all(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='main' AND table_type='BASE TABLE'"
            )
        }

        sim_df = snap_backend.query("SELECT * FROM simulations")  # noqa: F841 - referenced by DuckDB replacement scan in SQL below
        conn.execute("INSERT INTO simulations SELECT * FROM sim_df")

        for table in PER_SIM_TABLE_NAMES:
            if table not in pkg_tables:
                continue
            df = snap_backend.query(f"SELECT * FROM {table}")
            if df.empty:
                continue
            conn.execute(f"INSERT INTO {table} SELECT * FROM df")
    finally:
        snap.close()

    return sid


def _build_manifest(
    sim_id: str,
    staging: Path,
    geographic_fingerprint: str | None,
    *,
    inputs: list[dict] | None = None,
    project: str | None = None,
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
    inputs = inputs or []
    return {
        "format": HMP_MAGIC,
        "format_version": HMP_FORMAT_VERSION,
        "sim_id": sim_id,
        "project": project,
        "hydromodpy_version": _hydromodpy_version(),
        "geographic_fingerprint": geographic_fingerprint,
        "has_inputs": bool(inputs),
        "inputs": inputs,
        "files": files,
    }


def _write_ro_crate(catalog: Any, sim_id: str, staging: Path) -> Path | None:
    """Best-effort RO-Crate v1.1 sidecar at the staging root.

    Failures are logged and the package keeps going: the RO-Crate is a
    metadata bonus, never a hard requirement of the .hmp container.
    """
    try:
        from hydromodpy.results.export import write_ro_crate

        return write_ro_crate(catalog, sim_id, staging / RO_CRATE_METADATA_NAME)
    except Exception as exc:  # noqa: BLE001 - keep export resilient
        logger.warning("Failed to write RO-Crate inside .hmp staging: %s", exc)
        return None


def _write_readme(
    sim_id: str,
    dst: Path,
    *,
    n_inputs: int = 0,
) -> None:
    inputs_line = f"- **bundled input files**: {n_inputs}\n" if n_inputs else ""
    dst.write_text(
        (
            f"# HydroModPy simulation package\n\n"
            f"- **sim_id**: `{sim_id}`\n"
            f"- **format_version**: `{HMP_FORMAT_VERSION}`\n"
            f"- **hydromodpy_version**: `{_hydromodpy_version()}`\n"
            f"{inputs_line}\n"
            "Import with `Catalog.import_package(<path>.hmp)` "
            "or the `hmp add <archive>.hmp` CLI.\n"
            "Integrity of the archive is verified against `manifest.json` "
            "on import (SHA-256 per file).\n"
        ),
        encoding="utf-8",
    )


def _write_tar_zst(staging: Path, output: Path) -> None:
    """Pack ``staging`` (with a manifest at its root) into ``output`` (tar.zst).

    File order is deterministic (sorted) so the archive is reproducible.
    """
    import tempfile

    import zstandard as zstd

    files = sorted(staging.rglob("*"))
    output.parent.mkdir(parents=True, exist_ok=True)
    cctx = zstd.ZstdCompressor(level=10)
    # Stage the tar on disk (not in a BytesIO), then stream-compress it with its
    # known size so the whole uncompressed archive is never resident in memory
    # (a chronicle run is multi-GB) while the zstd frame still embeds the content
    # size, keeping it readable by one-shot decompressors.
    with tempfile.TemporaryDirectory() as tmpdir:
        tar_path = Path(tmpdir) / "archive.tar"
        with tarfile.open(str(tar_path), mode="w") as tar:
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
                with open(path, "rb") as inner:
                    tar.addfile(info, inner)
        tar_size = tar_path.stat().st_size
        with (
            open(tar_path, "rb") as src,
            open(output, "wb") as fh,
            cctx.stream_writer(fh, size=tar_size) as compressor,
        ):
            shutil.copyfileobj(src, compressor, length=1024 * 1024)


def _read_tar_zst(archive: Path, staging: Path) -> None:
    """Extract ``archive`` (tar.zst) into ``staging`` without buffering it all."""
    import zstandard as zstd

    dctx = zstd.ZstdDecompressor()
    with open(archive, "rb") as fh, dctx.stream_reader(fh) as reader:
        with tarfile.open(fileobj=reader, mode="r|") as tar:
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
        The source :class:`Catalog` instance (passed as ``Any`` to
        avoid a circular import).
    sim_id
        The simulation UUID to export.
    output_path
        Destination file path. The ``.hmp`` suffix is added when missing.

    Returns
    -------
    Path
        Written archive path.

    Raises
    ------
    KeyError
        Raised when ``sim_id`` is not present in the catalog.
    FileNotFoundError
        Raised when the simulation Zarr store is missing.

    Examples
    --------
    >>> export_hmp_package(catalog, run.sim_id, "baseline.hmp")
    """
    sid = str(sim_id)
    output = Path(output_path)
    if output.suffix != ".hmp":
        output = (
            output.with_suffix(output.suffix + ".hmp")
            if output.suffix
            else output.with_suffix(".hmp")
        )

    row = catalog.backend.fetch_one(
        "SELECT geographic_fingerprint, project FROM simulations WHERE sim_id = ?",
        [sid],
    )
    if row is None:
        raise KeyError(f"Simulation '{sid}' not found")
    geo_fp, project_name = row
    workspace = catalog.workspace_path
    zarr_src = catalog.fields_path_for(sid)

    with tempfile.TemporaryDirectory(prefix="hmp_export_") as tmpdir:
        staging = Path(tmpdir) / sid
        staging.mkdir()

        _dump_catalog_snapshot(
            catalog.connection,
            sid,
            staging / CATALOG_SNAPSHOT_NAME,
        )
        _pack_zarr(zarr_src, staging / ZARR_ARCHIVE_NAME)
        _materialise_geographic(workspace, geo_fp, staging)
        _materialise_parquet(catalog.tables_dir_for(sid), staging)
        sealed = _materialise_run_seal(catalog.run_dir_for(sid), staging)
        if RUN_MANIFEST_FILENAME not in sealed:
            logger.warning(
                "Run %s is not sealed: %s carries no %s, so the archive cannot "
                "be read back without an index.",
                sid[:8],
                output.name,
                RUN_MANIFEST_FILENAME,
            )
        inputs_manifest = _materialise_inputs(catalog, sid, staging)
        _write_ro_crate(catalog, sid, staging)
        _write_readme(
            sid,
            staging / README_NAME,
            n_inputs=len(inputs_manifest),
        )

        manifest = _build_manifest(
            sid,
            staging,
            geo_fp,
            inputs=inputs_manifest,
            project=project_name,
        )
        (staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        # Root the archive at the sim_id directory so consumers can see a
        # single top-level folder.
        _write_tar_zst(staging.parent, output)

    logger.info("Exported simulation %s to %s", sid, output)
    return output


def _read_snapshot_project(snap_path: Path) -> str | None:
    import duckdb as _duckdb

    snap = _duckdb.connect(str(snap_path), read_only=True)
    try:
        row = snap.execute("SELECT project FROM simulations LIMIT 1").fetchone()
    finally:
        snap.close()
    return str(row[0]) if row and row[0] else None


def _check_project_conflict(
    catalog: Any,
    manifest: dict,
    as_project: str | None,
) -> None:
    """Raise if the incoming project name collides without an explicit rename."""
    if as_project:
        return
    incoming_project = manifest.get("project")
    if not incoming_project:
        return
    existing_sid = catalog.backend.fetch_one(
        "SELECT sim_id FROM simulations WHERE project = ? LIMIT 1",
        [incoming_project],
    )
    if existing_sid is not None:
        raise ValueError(
            f"Project '{incoming_project}' already exists in this workspace. "
            "Use `--as <new_name>` to import under a different project name."
        )


def _rewrite_snapshot_project(snap_path: Path, new_project: str) -> None:
    import duckdb as _duckdb

    snap = _duckdb.connect(str(snap_path))
    try:
        snap.execute(
            "UPDATE simulations SET project = ?",
            [new_project],
        )
    finally:
        snap.close()


def _rewrite_snapshot_paths(snap_path: Path, rewrites: dict[str, str]) -> None:
    """Rewrite stored config JSON so the input paths point at their new home."""
    if not rewrites:
        return
    import duckdb as _duckdb

    snap = _duckdb.connect(str(snap_path))
    try:
        rows = snap.execute(
            "SELECT sim_id, config_toml, config_snapshot FROM simulations"
        ).fetchall()
        for sim_id, config_toml, config_snapshot in rows:
            new_toml = _rewrite_paths_in_json_blob(config_toml, rewrites)
            new_snap = _rewrite_paths_in_json_blob(config_snapshot, rewrites)
            if new_toml is not None or new_snap is not None:
                snap.execute(
                    "UPDATE simulations "
                    "SET config_toml = COALESCE(?, config_toml), "
                    "    config_snapshot = COALESCE(?, config_snapshot) "
                    "WHERE sim_id = ?",
                    [new_toml, new_snap, sim_id],
                )
        for old_path, new_path in rewrites.items():
            snap.execute(
                """UPDATE tracked_files
                   SET original_path = ?,
                       canonical_path = ?,
                       portable = TRUE
                   WHERE original_path = ? OR canonical_path = ?""",
                [new_path, new_path, old_path, old_path],
            )
    finally:
        snap.close()


def _rewrite_paths_in_json_blob(
    raw: str | None,
    rewrites: dict[str, str],
) -> str | None:
    if not raw:
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return None
    changed = _apply_rewrites_recursive(payload, rewrites)
    if not changed:
        return None
    return json.dumps(payload)


def _apply_rewrites_recursive(
    node: Any,
    rewrites: dict[str, str],
) -> bool:
    changed = False
    if isinstance(node, dict):
        for key, val in list(node.items()):
            if isinstance(val, str) and val in rewrites:
                node[key] = rewrites[val]
                changed = True
            else:
                if _apply_rewrites_recursive(val, rewrites):
                    changed = True
    elif isinstance(node, list):
        for i, val in enumerate(node):
            if isinstance(val, str) and val in rewrites:
                node[i] = rewrites[val]
                changed = True
            else:
                if _apply_rewrites_recursive(val, rewrites):
                    changed = True
    return changed


def import_hmp_package(
    catalog: Any,
    package_path: Path | str,
    *,
    force: bool = False,
    as_project: str | None = None,
    dematerialise_inputs: bool = True,
    dry_run: bool = False,
    allow_existing_project: bool = False,
) -> str:
    """Import a ``.hmp`` archive into the given catalog's workspace.

    Verifies every file listed in ``manifest.json`` before any catalog
    mutation. When ``dematerialise_inputs`` is true and the archive
    carries an ``inputs/`` bundle, input files are copied into the
    workspace ``data/`` layout and the stored config paths are rewritten
    to point at the new locations. ``as_project`` overrides the project
    column in the snapshot (useful when the target workspace already
    owns a project with the incoming name). ``dry_run`` extracts and
    validates the archive but skips every mutation.
    """
    archive = Path(package_path)
    if not archive.is_file():
        raise FileNotFoundError(f"No .hmp archive at {archive}")

    with tempfile.TemporaryDirectory(prefix="hmp_import_") as tmpdir:
        staging = Path(tmpdir)
        _read_tar_zst(archive, staging)

        roots = [p for p in staging.iterdir() if p.is_dir()]
        if len(roots) != 1:
            raise ValueError(
                f"Expected exactly one top-level directory in archive, found {len(roots)}"
            )
        pkg = roots[0]

        manifest_path = pkg / MANIFEST_NAME
        if not manifest_path.is_file():
            raise ValueError(f"{MANIFEST_NAME} is missing from the archive")
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("format") != HMP_MAGIC:
            raise ValueError(f"Unexpected archive format: {manifest.get('format')!r}")
        sid = str(manifest["sim_id"])

        for entry in manifest["files"]:
            path = pkg / entry["path"]
            if not path.is_file():
                raise ValueError(f"Archive is missing file listed in manifest: {entry['path']}")
            actual = _sha256_file(path)
            if actual != entry["sha256"]:
                raise ValueError(
                    f"SHA-256 mismatch for {entry['path']}: "
                    f"expected {entry['sha256']}, got {actual}"
                )

        existing = catalog.backend.fetch_one(
            "SELECT sim_id FROM simulations WHERE sim_id = ?",
            [sid],
        )
        if existing is not None:
            if not force:
                raise ValueError(f"Simulation '{sid}' already exists. Use force=True to overwrite.")
        elif not allow_existing_project:
            _check_project_conflict(catalog, manifest, as_project)

        if dry_run:
            return sid

        if existing is not None:
            catalog.delete(sid)

        snap_path = pkg / CATALOG_SNAPSHOT_NAME
        if not snap_path.is_file():
            raise ValueError(f"{CATALOG_SNAPSHOT_NAME} missing from archive")

        rewrites: dict[str, str] = {}
        if dematerialise_inputs and manifest.get("has_inputs"):
            from hydromodpy.results.importers import (
                dematerialise_inputs as _dematerialise,
            )

            rewrites = _dematerialise(pkg, catalog.workspace_path, manifest)

        if as_project:
            _rewrite_snapshot_project(snap_path, as_project)
        _rewrite_snapshot_paths(snap_path, rewrites)

        with catalog.backend.transaction():
            # _restore_catalog_snapshot still takes a raw DuckDB connection
            # because the snapshot file is a transient one-sim DuckDB and is
            # DuckDB-only by construction (.hmp archive contract).
            _restore_catalog_snapshot(catalog.connection, snap_path)
            workspace = catalog.workspace_path
            # The restored row carries the run name, so the path resolver names
            # the run directory exactly as a local run would.
            dirname = catalog.run_dir_for(sid).name
            catalog.backend.execute(
                "UPDATE simulations SET zarr_path = ?, storage_basename = ? WHERE sim_id = ?",
                [f"{RUNS_DIRNAME}/{dirname}/{FIELDS_STORE_NAME}", dirname, sid],
            )

        _unpack_zarr(pkg / ZARR_ARCHIVE_NAME, catalog.fields_path_for(sid))
        _dematerialise_parquet(pkg, catalog.tables_dir_for(sid))
        _dematerialise_run_seal(pkg, catalog.run_dir_for(sid))
        # Refresh Parquet views so the freshly-materialised files become
        # visible to subsequent ``SELECT ... FROM <view>`` calls on the
        # caller's catalog connection.
        from hydromodpy.results.catalog.parquet_views import ensure_parquet_views

        ensure_parquet_views(catalog.connection, catalog.runs_dir)

        _dematerialise_geographic(
            pkg,
            workspace,
            manifest.get("geographic_fingerprint"),
            overwrite=force,
        )

    logger.info("Imported simulation %s from %s", sid, archive)
    return sid


def export_hmp_package_multi(
    catalog: Any,
    sim_ids: list[str],
    output_path: Path | str,
) -> Path:
    """Export several simulations as one portable multi-run ``.hmp`` archive.

    Each run is bundled as a self-contained single-run archive under
    ``runs/<sim_id>.hmp`` and listed in a top-level v2.0 manifest. Import reuses
    the single-run path verbatim, and single-run archives stay readable.
    """
    ids = [str(s) for s in sim_ids]
    if not ids:
        raise ValueError("export_hmp_package_multi requires at least one sim_id")
    output = Path(output_path)
    if output.suffix != ".hmp":
        output = output.with_suffix(".hmp")

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        runs_dir = staging / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        runs_meta: list[dict] = []
        for sid in ids:
            inner = export_hmp_package(catalog, sid, runs_dir / f"{sid}.hmp")
            runs_meta.append(
                {
                    "sim_id": sid,
                    "rel_path": inner.relative_to(staging).as_posix(),
                    "sha256": _sha256_file(inner),
                }
            )
        manifest = {
            "format": HMP_MAGIC,
            "format_version": "2.0",
            "archive_type": "multi-run",
            "hydromodpy_version": _hydromodpy_version(),
            "runs": runs_meta,
        }
        (staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        _write_tar_zst(staging, output)
    logger.info("Exported %d simulations to %s (multi-run)", len(ids), output)
    return output


def import_hmp_package_multi(
    catalog: Any,
    package_path: Path | str,
    *,
    force: bool = False,
    dematerialise_inputs: bool = True,
    dry_run: bool = False,
) -> list[str]:
    """Import a ``.hmp`` archive (single-run or multi-run); return the sim_ids.

    A single-run archive (no ``archive_type == "multi-run"``) is delegated to
    :func:`import_hmp_package`; a multi-run archive restores each nested run
    after verifying its SHA-256.
    """
    pkg = Path(package_path)
    if not pkg.is_file():
        raise FileNotFoundError(f"No archive at {pkg}")

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        _read_tar_zst(pkg, staging)
        # A multi-run container carries manifest.json at the archive root with
        # ``archive_type == "multi-run"``. A single-run archive instead nests its
        # payload under one top-level directory, so its root manifest is absent.
        root_manifest = staging / MANIFEST_NAME
        manifest: dict = {}
        if root_manifest.is_file():
            manifest = json.loads(root_manifest.read_text(encoding="utf-8"))
        if manifest.get("archive_type") != "multi-run":
            return [
                import_hmp_package(
                    catalog,
                    pkg,
                    force=force,
                    dematerialise_inputs=dematerialise_inputs,
                    dry_run=dry_run,
                )
            ]
        sids: list[str] = []
        for run in manifest.get("runs", []):
            inner = staging / run["rel_path"]
            if not inner.is_file():
                raise ValueError(f"multi-run archive is missing {run['rel_path']}")
            if _sha256_file(inner) != run.get("sha256"):
                raise ValueError(f"checksum mismatch for run {run.get('sim_id')}")
            # Runs in a container legitimately share a project, so allow the
            # project to already exist (the per-sim id guard still applies).
            sids.append(
                import_hmp_package(
                    catalog,
                    inner,
                    force=force,
                    dematerialise_inputs=dematerialise_inputs,
                    dry_run=dry_run,
                    allow_existing_project=True,
                )
            )
        logger.info("Imported %d simulations from %s (multi-run)", len(sids), pkg)
        return sids


__all__ = [
    "CACHE_DIRNAME",
    "GEOGRAPHIC_SUBDIR",
    "HMP_FORMAT_VERSION",
    "HMP_MAGIC",
    "INPUTS_SUBDIR",
    "INPUTS_MANIFEST_NAME",
    "MANIFEST_NAME",
    "export_hmp_package",
    "export_hmp_package_multi",
    "import_hmp_package",
    "import_hmp_package_multi",
]
