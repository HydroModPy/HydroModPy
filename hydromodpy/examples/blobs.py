"""Content-addressed cache for the files an example needs.

The unit that is cached is the FILE, not the example. ``examples/data/dem/
DEM_armorican_massif.tif`` is 90 MiB of the ~92 MiB example 04 needs, and 15 of
the example projects point at that same DEM: a zip per example would ship it
again every time, while a blob keyed by its sha256 is downloaded once and the
next example costs a few hundred kilobytes.

Blobs live under ``<cache>/examples/blobs/<sha256[:2]>/<sha256>``, beside the
solver binaries ``hmp install-binaries`` caches.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from hydromodpy.core import progress
from hydromodpy.core.exceptions import CacheCorruptionError, NetworkError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import cache_dir
from hydromodpy.core.version import __version__
from hydromodpy.examples.manifest import ExampleFile

logger = get_logger(__name__)

SOURCE_ENV = "HMP_EXAMPLES_SOURCE"
"""Environment variable that replaces the whole ``<base>/<ref>`` prefix."""

DEFAULT_BASE_URL = "https://raw.githubusercontent.com/HydroModPy/HydroModPy"

PROGRESS_THRESHOLD_BYTES = 4 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024
_TIMEOUT_SECONDS = 60


def default_ref() -> str:
    """Return the git ref an install fetches from by default."""
    return f"v{__version__}"


def resolve_source(ref: str | None = None) -> str:
    """Return the root every ``repo_path`` is appended to.

    ``HMP_EXAMPLES_SOURCE`` replaces the whole prefix, ref included, so the
    same code path serves a release tag on GitHub, a ``file://`` URL and a
    local checkout. That is one rule and not a special case: when the variable
    is set, ``--ref`` no longer applies.
    """
    override = os.environ.get(SOURCE_ENV)
    if override:
        return override.rstrip("/")
    return f"{DEFAULT_BASE_URL}/{ref or default_ref()}"


def blobs_dir() -> Path:
    """Return ``<cache>/examples/blobs/``, creating it on demand."""
    target = Path(cache_dir()) / "examples" / "blobs"
    target.mkdir(parents=True, exist_ok=True)
    return target


def blob_path(sha256: str) -> Path:
    """Return the cache path of one blob, whether it is there or not."""
    return blobs_dir() / sha256[:2] / sha256


def is_cached(item: ExampleFile) -> bool:
    """Return True when this file is already in the blob cache."""
    return blob_path(item.sha256).is_file()


def missing_bytes(items: tuple[ExampleFile, ...]) -> int:
    """Return how many bytes of ``items`` are not cached on this machine."""
    seen: set[str] = set()
    total = 0
    for item in items:
        if item.sha256 in seen or is_cached(item):
            continue
        seen.add(item.sha256)
        total += item.size
    return total


def sha256_of(path: Path) -> str:
    """Return the sha256 of a file on disk, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_blob(item: ExampleFile, *, source: str) -> Path:
    """Return the cached blob for ``item``, fetching it from ``source`` if missing.

    A sha256 that does not match what the manifest declares is a hard failure:
    the offending blob is deleted and the error names the file and where the
    bytes came from. This holds for a cache hit as much as for a download. The
    blob's own name is its hash, so a cache hit that hashes to something else
    is corruption, and handing it to the workspace unchecked would write a
    silently wrong input file that every later step trusts.
    """
    target = blob_path(item.sha256)
    if target.is_file():
        cached = sha256_of(target)
        if cached == item.sha256:
            logger.debug("example blob already cached: %s (%s)", item.repo_path, item.sha256[:12])
            return target
        target.unlink(missing_ok=True)
        raise CacheCorruptionError(
            f"The cached blob for {item.repo_path} hashes to {cached}, not to the "
            f"{item.sha256} the manifest declares and the cache keys it under. It has "
            f"been removed from the cache; run the same command again to fetch a clean "
            f"copy.",
            repo_path=item.repo_path,
            source=str(target),
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f"{item.sha256}.{os.getpid()}.part")
    origin = f"{source}/{_encode(item.repo_path)}"
    try:
        digest = _download(origin, partial, label=Path(item.dest).name, size=item.size)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    if digest != item.sha256:
        partial.unlink(missing_ok=True)
        raise CacheCorruptionError(
            f"Checksum mismatch for {item.repo_path} fetched from {origin}: "
            f"the manifest declares sha256={item.sha256}, the download hashes to "
            f"{digest}. Nothing was written to the cache.",
            repo_path=item.repo_path,
            source=origin,
        )

    partial.replace(target)
    logger.info("cached example blob %s (%d bytes)", item.repo_path, item.size)
    return target


def _encode(repo_path: str) -> str:
    """Percent-encode a repository path, keeping the separators readable."""
    return quote(repo_path, safe="/._-")


def _download(origin: str, destination: Path, *, label: str, size: int) -> str:
    """Stream ``origin`` into ``destination`` and return the sha256 it hashed to."""
    digest = hashlib.sha256()
    show_progress = size >= PROGRESS_THRESHOLD_BYTES
    with _open_source(origin) as reader, destination.open("wb") as writer:
        if show_progress:
            with progress.task(f"Fetching {label}", total=float(size), unit="bytes") as handle:
                for chunk in iter(lambda: reader.read(_CHUNK_BYTES), b""):
                    digest.update(chunk)
                    writer.write(chunk)
                    handle.advance(len(chunk))
        else:
            shutil.copyfileobj(_HashingReader(reader, digest), writer, _CHUNK_BYTES)
    return digest.hexdigest()


class _HashingReader:
    """Wrap a reader so ``copyfileobj`` hashes what it copies."""

    def __init__(self, reader, digest) -> None:  # noqa: ANN001 - stdlib duck types
        self._reader = reader
        self._digest = digest

    def read(self, size: int = -1) -> bytes:
        chunk = self._reader.read(size)
        self._digest.update(chunk)
        return chunk


def _open_source(origin: str):  # noqa: ANN201 - a binary reader, stdlib duck type
    """Open ``origin`` for reading, over HTTP or from the local filesystem."""
    if origin.startswith(("http://", "https://")):
        try:
            return urllib.request.urlopen(origin, timeout=_TIMEOUT_SECONDS)  # noqa: S310
        except urllib.error.HTTPError as exc:
            raise NetworkError(
                f"{origin} answered HTTP {exc.code}. Check the --ref: the tag has to "
                f"exist on the repository before its files can be fetched.",
                source=origin,
                status=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            raise NetworkError(f"Cannot reach {origin}: {exc.reason}.", source=origin) from exc

    local = Path(origin[len("file://") :] if origin.startswith("file://") else origin)
    if not local.is_file():
        raise NetworkError(
            f"{local} does not exist. {SOURCE_ENV} points at a local tree, so every "
            f"repo_path of the manifest has to resolve under it.",
            source=str(local),
        )
    return local.open("rb")
