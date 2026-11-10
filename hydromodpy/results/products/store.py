"""The product store under ``<project>/.hmp/products/``.

A product is a directory written once under a temporary name, then renamed to
its key. The store knows no product type and no configuration: a product is a
folder whose name is a sha256 key, with a ``meta.json`` that says what it is.
Eviction removes the oldest written product first and never one a running
attempt cites, then sweeps the temporary and trash folders of dead writers.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from hydromodpy.core.io.lock_file import LockFile
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import PRODUCTS_DIRNAME, internal_dir
from hydromodpy.results.outcome import death_is_proven

logger = get_logger(__name__)

META_FILENAME = "meta.json"
"""Name of the one file every product carries."""

TMP_DIRNAME = ".tmp"
TRASH_DIRNAME = ".trash"
LOCKS_DIRNAME = ".locks"

STALE_AFTER_S = 6 * 3600.0
"""Age past which a store lock is taken back, even while its holder runs."""

WAIT_S = 120.0
"""How long a writer waits for the lock of a key before building without it."""

SWEEP_AFTER_S = 24 * 3600.0
"""Age past which a temporary or trash folder goes, whatever its writer."""

_KEY = re.compile(r"^[0-9a-f]{64}$")
"""A key is a sha256 in hexadecimal."""


def products_root(project_root: Path | str) -> Path:
    """Return ``<project>/.hmp/products/``, the root of the store."""
    return internal_dir(Path(project_root)) / PRODUCTS_DIRNAME


@dataclass(frozen=True, slots=True)
class Entry:
    """One stored product, read from its ``meta.json``."""

    key: str
    kind: str
    bytes: int
    written_at: float


@dataclass(frozen=True, slots=True)
class EvictReport:
    """What one eviction did. Sizes are in bytes."""

    removed: tuple[str, ...]
    protected: tuple[str, ...]
    freed: int
    total_after: int
    over_cap: bool


class ProductStore:
    """Shared, disposable store of stage products."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def path(self, key: str) -> Path:
        """Directory of a key, two characters of fan-out."""
        _check_key(key)
        return self.root / key[:2] / key

    def get(self, key: str) -> Path | None:
        """Return the product directory, or ``None``. A read never changes the store."""
        path = self.path(key)
        return path if (path / META_FILENAME).is_file() else None

    def entries(self) -> list[Entry]:
        """List the stored products, an unreadable or evicted one counted as absent."""
        out: list[Entry] = []
        for meta_path in sorted(self.root.glob("??/*/meta.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                out.append(Entry(meta["key"], meta["kind"], meta["bytes"], meta["written_at"]))
            except (FileNotFoundError, ValueError, OSError, KeyError):
                continue
        return out

    def put(self, key: str, kind: str, write: Callable[[Path], None]) -> Path:
        """Return the product of ``key``, calling ``write`` only when it is absent."""
        _check_key(key)
        self.root.mkdir(parents=True, exist_ok=True)
        lock = LockFile(self._lock_path(key), stale_after_s=STALE_AFTER_S, wait_s=WAIT_S)
        held = lock.acquire()
        if not held:
            logger.warning(
                "The lock of product %s was not taken within %ss; building without it.",
                key,
                WAIT_S,
            )
        try:
            if (hit := self.get(key)) is not None:
                return hit
            return self._build(key, kind, write)
        finally:
            if held:
                lock.release()

    def discard(self, key: str) -> None:
        """Remove a product that cannot be read, so the next read rebuilds it."""
        _check_key(key)
        target = self.path(key)
        if not target.exists():
            return
        trash = self._trash_path(key)
        trash.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(target, trash)
        except FileNotFoundError:
            return
        shutil.rmtree(trash, ignore_errors=True)

    def evict(
        self,
        cap_bytes: int,
        *,
        keep: Iterable[str] = (),
        dry_run: bool = False,
    ) -> EvictReport:
        """Remove the oldest products until the total fits ``cap_bytes``."""
        protected = frozenset(keep)
        entries = sorted(self.entries(), key=lambda entry: (entry.written_at, entry.key))
        total = sum(entry.bytes for entry in entries)
        removed: list[str] = []
        protected_keys: list[str] = []
        freed = 0
        for entry in entries:
            if total <= cap_bytes:
                break
            if entry.key in protected:
                protected_keys.append(entry.key)
                continue
            if not dry_run:
                self.discard(entry.key)
            removed.append(entry.key)
            freed += entry.bytes
            total -= entry.bytes
        if not dry_run:
            self._sweep()
        over_cap = sum(entry.bytes for entry in entries if entry.key in protected) > cap_bytes
        return EvictReport(tuple(removed), tuple(protected_keys), freed, total, over_cap)

    def _build(self, key: str, kind: str, write: Callable[[Path], None]) -> Path:
        tmp = self._tmp_path(key)
        tmp.mkdir(parents=True)
        try:
            write(tmp)
            meta = {"key": key, "kind": kind, "bytes": _tree_size(tmp), "written_at": time.time()}
            (tmp / META_FILENAME).write_text(json.dumps(meta), encoding="utf-8")
            target = self.path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(tmp, target)
            except OSError:
                if not (target / META_FILENAME).is_file():
                    raise
                # A neighbour built the same product while this writer held no lock.
            return target
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _lock_path(self, key: str) -> Path:
        return self.root / LOCKS_DIRNAME / f"{key}.lock"

    def _tmp_path(self, key: str) -> Path:
        suffix = uuid.uuid4().hex[:8]
        return self.root / TMP_DIRNAME / f"{key}.{socket.gethostname()}.{os.getpid()}.{suffix}"

    def _trash_path(self, key: str) -> Path:
        suffix = uuid.uuid4().hex[:8]
        return self.root / TRASH_DIRNAME / f"{key}.{socket.gethostname()}.{os.getpid()}.{suffix}"

    def _sweep(self) -> None:
        """Remove temporary and trash folders of a dead writer, or older than a day."""
        for sub in (self.root / TMP_DIRNAME, self.root / TRASH_DIRNAME):
            if not sub.is_dir():
                continue
            for path in sorted(sub.iterdir()):
                if path.is_dir() and _expired(path):
                    shutil.rmtree(path, ignore_errors=True)


def _check_key(key: str) -> None:
    if _KEY.fullmatch(key) is None:
        raise ValueError(f"not a product key: {key!r}, a sha256 in hexadecimal is expected")


def _tree_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _writer(name: str) -> tuple[str | None, int | None]:
    parts = name.rsplit(".", 3)
    if len(parts) != 4:
        return None, None
    try:
        return parts[1], int(parts[2])
    except ValueError:
        return None, None


def _expired(path: Path) -> bool:
    host, pid = _writer(path.name)
    if death_is_proven(host, pid):
        return True
    return time.time() - path.stat().st_mtime > SWEEP_AFTER_S


__all__ = [
    "LOCKS_DIRNAME",
    "META_FILENAME",
    "STALE_AFTER_S",
    "SWEEP_AFTER_S",
    "TRASH_DIRNAME",
    "TMP_DIRNAME",
    "WAIT_S",
    "Entry",
    "EvictReport",
    "ProductStore",
    "products_root",
]
