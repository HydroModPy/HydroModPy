"""Pack the data cache of a workspace into one archive, and restore it elsewhere.

An archive holds ``hydromodpy.lock`` at its top and, for each row of the
cache, the file and its sidecar under ``artefacts/<sha256>/``. Restoring it
checks every file the lockfile names before anything is written, then puts
each file and its sidecar back at its place in the data folder, so the
restored files are rows of the cache at once. ``.tar``, ``.tar.gz`` and
``.tar.zst`` are written and read; the last needs ``zstandard``.

An archive of HydroModPy 2.0.0 carries a lockfile ``hydromodpy.lock.v1`` and
no sidecar. Its lockfile is refused with the sentence that names
``hmp data lock``.
"""

from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
from pathlib import Path

from hydromodpy.core.exceptions import CacheCorruptionError
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.data.provenance.lockfile import (
    LOCKFILE_NAME,
    USER_FILE_SOURCE,
    LockedInput,
    read_lockfile_inputs,
    write_lockfile,
)
from hydromodpy.data.provenance.sidecars import SIDECAR_SUFFIX, CacheIndex, sidecar_path_for

ARTEFACTS_DIRNAME = "artefacts"


def _open_writer(dest: Path):
    if dest.suffix == ".zst":
        try:
            import zstandard as zstd  # type: ignore[import-untyped]
        except ImportError as exc:
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
        except ImportError as exc:
            raise RuntimeError("zstandard is required to read .tar.zst archives.") from exc
        raw = open(src, "rb")
        dctx = zstd.ZstdDecompressor()
        return dctx.stream_reader(raw), raw, "r|"
    if src.suffix in (".gz", ".tgz"):
        return open(src, "rb"), None, "r:gz"
    return open(src, "rb"), None, "r"


def _artefact(item: LockedInput) -> str:
    """Where a record lands in the archive. An empty row has no bytes, only its sidecar."""
    if item.empty:
        return f"{ARTEFACTS_DIRNAME}/empty/{item.variable}/{Path(item.path).name}"
    return f"{ARTEFACTS_DIRNAME}/{item.sha256}/{Path(item.path).name}"


def archive_data(data_root: Path, dest: Path | str, *, lockfile_dest: Path | None = None) -> Path:
    """Write the archive of every row under *data_root* to *dest*. Returns *dest*.

    The lockfile written for the archive lands at *lockfile_dest*, by default
    beside *dest*. Each file goes in with its sidecar, and an empty answer
    with its sidecar alone.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    lockfile_dest = Path(lockfile_dest) if lockfile_dest else dest.parent / LOCKFILE_NAME
    write_lockfile(lockfile_dest, data_root)
    index = CacheIndex(data_root)
    stream, raw, mode = _open_writer(dest)
    try:
        with tarfile.open(fileobj=stream, mode=mode) as tar:
            tar.add(lockfile_dest, arcname=LOCKFILE_NAME)
            for item in read_lockfile_inputs(lockfile_dest):
                path = index.resolve(item.path)
                name = _artefact(item)
                if item.empty:
                    if sidecar_path_for(path).is_file():
                        tar.add(sidecar_path_for(path), arcname=name + SIDECAR_SUFFIX)
                    continue
                if not path.is_file():
                    continue
                tar.add(path, arcname=name)
                tar.add(sidecar_path_for(path), arcname=name + SIDECAR_SUFFIX)
    finally:
        stream.close()
        if raw is not None:
            raw.close()
    return dest


def restore_archive(archive: Path | str, data_root: Path | str) -> list[Path]:
    """Put back every file of *archive* and its sidecar under *data_root*.

    The archive is read in a staging folder beside *data_root*. A file that is
    absent, holds other bytes or comes without its sidecar refuses the whole
    archive, each one named, and nothing is written. The sidecar of an empty
    answer goes back alone. Returns the files put back.
    """
    archive = Path(archive)
    data_root = Path(data_root).expanduser().resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{data_root.name}.restore.", dir=data_root.parent))
    try:
        stream, raw, mode = _open_reader(archive)
        try:
            with tarfile.open(fileobj=stream, mode=mode) as tar:
                tar.extractall(staging, filter="data")
        finally:
            stream.close()
            if raw is not None:
                raw.close()
        items = _checked_items(archive, staging, data_root)
        restored: list[Path] = []
        placed: dict[str, Path] = {}
        for item in items:
            target = data_root / item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            name = _artefact(item)
            if item.empty:
                os.replace(sidecar_path_for(staging / name), sidecar_path_for(target))
                continue
            # Two rows of the same bytes and name share one artefact: the
            # second is copied from the first, already in place.
            source = placed.get(name, staging / name)
            if name in placed:
                shutil.copy2(source, target)
                shutil.copy2(sidecar_path_for(source), sidecar_path_for(target))
            else:
                os.replace(source, target)
                os.replace(sidecar_path_for(source), sidecar_path_for(target))
                placed[name] = target
            restored.append(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return restored


def _inside(folder: Path, relative: str) -> bool:
    """Say whether *relative*, read from a lockfile, names a place inside *folder*."""
    if Path(relative).is_absolute():
        return False
    return (folder / relative).resolve().is_relative_to(folder.resolve())


def _checked_items(archive: Path, extracted: Path, data_root: Path) -> list[LockedInput]:
    """Return the records of the archive once each one is checked, or refuse it.

    The lockfile of an archive comes from elsewhere, so a record whose path
    leaves *data_root*, or whose artefact leaves the extracted folder, is
    refused like a missing file.
    """
    lockfile_path = extracted / LOCKFILE_NAME
    if not lockfile_path.is_file():
        raise CacheCorruptionError(
            f"{archive} holds no {LOCKFILE_NAME}, so nothing in it can be checked. "
            "Nothing was restored. Write it again with `hmp data archive --to FILE`."
        )
    items = [i for i in read_lockfile_inputs(lockfile_path) if i.source != USER_FILE_SOURCE]
    faults: list[str] = []
    for item in items:
        if not _inside(data_root, item.path):
            faults.append(f"{item.path}: this path leaves the data folder {data_root}")
            continue
        if not _inside(extracted, _artefact(item)):
            faults.append(f"{item.path}: its place in the archive leaves the archive")
            continue
        candidate = extracted / _artefact(item)
        if item.empty:
            if not sidecar_path_for(candidate).is_file():
                faults.append(f"{item.path}: the sidecar of its empty answer is absent")
            continue
        if not candidate.is_file():
            faults.append(f"{item.path}: absent from the archive")
            continue
        if not sidecar_path_for(candidate).is_file():
            faults.append(f"{item.path}: its sidecar is absent from the archive")
            continue
        actual = sha256_of(candidate)
        if actual != item.sha256:
            faults.append(f"{item.path}: expected sha256 {item.sha256}, got {actual}")
    if faults:
        raise CacheCorruptionError(
            f"{archive} does not hold what its {LOCKFILE_NAME} names, so nothing was restored. "
            "Write it again with `hmp data archive --to FILE`:\n  " + "\n  ".join(faults)
        )
    return items


__all__ = ["ARTEFACTS_DIRNAME", "archive_data", "restore_archive"]
