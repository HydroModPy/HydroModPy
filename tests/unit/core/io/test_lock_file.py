"""The exclusive file lock: taken, refused, taken back, and released by its owner."""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

from hydromodpy.core.io.lock_file import LockFile


def _write_lock(path: Path, *, pid: int, created: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pid": pid, "host": socket.gethostname(), "created": created}),
        encoding="utf-8",
    )


def test_a_lock_is_taken_then_released(tmp_path: Path) -> None:
    lock = LockFile(tmp_path / "x.lock")
    assert lock.acquire() is True
    assert lock.read() is not None
    assert lock.read().pid == os.getpid()
    lock.release()
    assert lock.read() is None


def test_a_held_lock_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    holder = LockFile(path)
    assert holder.acquire() is True
    assert LockFile(path, wait_s=0.0).acquire() is False
    holder.release()


def test_a_lock_of_a_dead_pid_is_taken_back(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    _write_lock(path, pid=2**30, created=time.time())
    lock = LockFile(path, wait_s=0.0)
    assert lock.acquire() is True
    assert lock.read().pid == os.getpid()
    lock.release()


def test_a_lock_too_old_is_taken_back(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    _write_lock(path, pid=os.getpid(), created=time.time() - 10 * 3600)
    lock = LockFile(path, stale_after_s=3600, wait_s=0.0)
    assert lock.acquire() is True
    lock.release()


def test_a_wait_that_expires_returns_false(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    holder = LockFile(path)
    assert holder.acquire() is True
    assert LockFile(path, wait_s=0.05).acquire() is False
    holder.release()


def test_a_release_does_not_remove_anothers_lock(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    _write_lock(path, pid=2**30, created=time.time())
    other = LockFile(path)
    other.held = True
    other.release()
    assert path.exists()
    assert other.held is False
