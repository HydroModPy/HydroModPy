"""The exclusive file lock: taken, refused, taken back, renewed, and released by its owner."""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

import pytest

from hydromodpy.core.io.lock_file import TORN_AFTER_S, LockFile


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


@pytest.mark.parametrize("content", [b"", b'{"pid": 12, "ho'], ids=["empty", "cut-json"])
@pytest.mark.parametrize(
    ("age_s", "taken"),
    [(TORN_AFTER_S + 60, True), (0.0, False)],
    ids=["old", "young"],
)
def test_a_lock_that_does_not_read_is_stale_once_old(tmp_path: Path, content, age_s, taken) -> None:
    path = tmp_path / "x.lock"
    path.write_bytes(content)
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))

    lock = LockFile(path, wait_s=0.0)

    assert lock.acquire() is taken
    if taken:
        assert lock.read().pid == os.getpid()
        lock.release()
    else:
        assert path.read_bytes() == content


def test_still_held_follows_the_file(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    lock = LockFile(path)
    assert lock.still_held() is False
    assert lock.acquire() is True
    assert lock.still_held() is True

    _write_lock(path, pid=os.getpid(), created=time.time() + 1)

    assert lock.still_held() is False, "another lock object took the place"
    lock.release()
    assert path.exists(), "a release leaves the lock of another holder"


def test_two_lock_objects_of_one_process_exclude_each_other(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    first = LockFile(path)
    assert first.acquire() is True

    second = LockFile(path, wait_s=0.0)

    assert second.acquire() is False
    assert second.still_held() is False
    second.release()
    assert first.still_held() is True
    first.release()


def test_renew_dates_the_lock_again(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    lock = LockFile(path)
    assert lock.acquire() is True
    first = lock.read().created

    time.sleep(0.01)
    lock.renew()

    assert lock.read().created > first
    assert lock.read().pid == os.getpid()
    assert lock.still_held() is True
    assert list(tmp_path.glob("*.tmp")) == []
    lock.release()
    assert not path.exists()


def test_renew_leaves_the_lock_of_another_alone(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    lock = LockFile(path)
    assert lock.acquire() is True
    _write_lock(path, pid=2**30, created=123.0)

    lock.renew()

    assert lock.read().pid == 2**30
    assert lock.read().created == 123.0


def test_renew_without_the_lock_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    LockFile(path).renew()
    assert not path.exists()


def test_a_fresh_lock_taken_between_verdict_and_take_back_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    _write_lock(path, pid=2**30, created=time.time())
    late = LockFile(path, wait_s=0.0)
    first = LockFile(path, wait_s=0.0)
    judged = LockFile.is_stale

    def judge_then_lose_the_race(self: LockFile, info) -> bool:
        verdict = judged(self, info)
        if self is late and not first.held:
            assert first.acquire() is True
        return verdict

    late.is_stale = judge_then_lose_the_race.__get__(late)

    assert late.acquire() is False
    assert first.still_held() is True
    assert late.held is False
    assert list(tmp_path.iterdir()) == [path]
    first.release()


def test_threads_racing_on_a_stale_lock_leave_one_holder(tmp_path: Path) -> None:
    import threading

    for round_ in range(30):
        path = tmp_path / f"r{round_}.lock"
        _write_lock(path, pid=2**30, created=time.time())
        locks = [LockFile(path, wait_s=0.0) for _ in range(8)]
        barrier = threading.Barrier(len(locks))
        taken: list[bool] = [False] * len(locks)

        def take(lock: LockFile, index: int, barrier=barrier, taken=taken) -> None:
            barrier.wait()
            taken[index] = lock.acquire()

        threads = [threading.Thread(target=take, args=(lock, i)) for i, lock in enumerate(locks)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sum(taken) == 1, f"round {round_}: {sum(taken)} holders"
        assert sum(lock.still_held() for lock in locks) == 1


def test_renew_does_not_overwrite_a_lock_taken_back_after_its_check(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    lock = LockFile(path)
    assert lock.acquire() is True
    other = tmp_path / "other"
    _write_lock(other, pid=2**30, created=123.0)
    os.replace(other, path)
    lock.still_held = lambda: True

    lock.renew()

    assert LockFile(path).read().created == 123.0
