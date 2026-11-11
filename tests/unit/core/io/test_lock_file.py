"""The exclusive file lock: taken, refused, taken back, renewed, and released by its owner."""

from __future__ import annotations

import errno
import json
import logging
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from hydromodpy.core.io import filesystem, lock_file
from hydromodpy.core.io.lock_file import TORN_AFTER_S, LockFile
from hydromodpy.core.state.host import host_name
from tests._helpers.windows_os import PatchedOs, WindowsOs


def _write_lock(path: Path, *, pid: int, created: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pid": pid, "host": host_name(), "created": created}),
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


# --- Windows refuses to rename or remove a file a reader holds open.


@pytest.fixture
def lock_warnings(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """The warnings of the lock logger, whatever the propagation of its parents."""
    lock_file.logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING):
            yield caplog
    finally:
        lock_file.logger.removeHandler(caplog.handler)


@pytest.fixture
def no_wait(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The waits of the retries, recorded instead of slept; the lock module reads as Windows."""
    waited: list[float] = []
    monkeypatch.setattr(filesystem.time, "sleep", waited.append)
    monkeypatch.setattr(lock_file, "os", WindowsOs())
    return waited


def _in_use(failures: int, then):
    """A function that fails as Windows does ``failures`` times, then calls ``then``."""
    calls = [0]

    def call(*args):
        calls[0] += 1
        if calls[0] <= failures:
            raise PermissionError(errno.EACCES, "The file is used by another process")
        return then(*args)

    return call


@pytest.mark.parametrize("operation", ["replace", "unlink"])
def test_a_release_refused_twice_still_removes_the_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_wait: list[float],
    lock_warnings: pytest.LogCaptureFixture,
    operation: str,
) -> None:
    path = tmp_path / "x.lock"
    lock = LockFile(path)
    assert lock.acquire() is True
    patched = PatchedOs(name="nt", **{operation: _in_use(2, getattr(os, operation))})
    monkeypatch.setattr(filesystem, "os", patched)

    lock.release()

    assert list(tmp_path.iterdir()) == []
    assert no_wait == pytest.approx([0.01, 0.02])
    assert lock_warnings.records == []


def test_a_release_refused_six_times_leaves_the_lock_and_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_wait: list[float],
    lock_warnings: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "x.lock"
    lock = LockFile(path)
    assert lock.acquire() is True
    mine = lock.read()
    monkeypatch.setattr(filesystem, "os", PatchedOs(name="nt", replace=_in_use(6, os.replace)))

    lock.release()

    assert lock.held is False
    assert list(tmp_path.iterdir()) == [path]
    assert LockFile(path).read() == mine
    assert sum(no_wait) == pytest.approx(0.31)
    assert any("stays in place until it is stale" in r.getMessage() for r in lock_warnings.records)


def test_a_lock_left_by_a_failed_release_is_taken_back_once_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_wait: list[float]
) -> None:
    path = tmp_path / "x.lock"
    lock = LockFile(path)
    assert lock.acquire() is True
    with monkeypatch.context() as patch:
        patch.setattr(filesystem, "os", PatchedOs(name="nt", replace=_in_use(6, os.replace)))
        lock.release()
    assert path.exists()

    later = LockFile(path, stale_after_s=0.0, wait_s=0.0)
    assert later.acquire() is True
    later.release()
    assert not path.exists()


def test_a_take_back_refused_by_a_reader_waits_and_keeps_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_wait: list[float]
) -> None:
    path = tmp_path / "x.lock"
    _write_lock(path, pid=2**30, created=time.time())
    patched = PatchedOs(name="nt", replace=_in_use(10**6, os.replace))
    monkeypatch.setattr(filesystem, "os", patched)

    assert LockFile(path, wait_s=0.0).acquire() is False

    assert LockFile(path).read().pid == 2**30
    assert list(tmp_path.iterdir()) == [path]


def test_a_lock_put_back_where_links_are_refused_is_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "x.lock"
    lock = LockFile(path)
    assert lock.acquire() is True
    other = tmp_path / "other"
    _write_lock(other, pid=2**30, created=123.0)
    os.replace(other, path)
    lock.still_held = lambda: True

    def refuse(source, target):
        raise PermissionError(errno.EPERM, "Incorrect function")

    monkeypatch.setattr(filesystem, "os", PatchedOs(link=refuse))
    lock.release()

    assert list(tmp_path.iterdir()) == [path]
    assert LockFile(path).read().created == 123.0


def test_a_lock_put_back_by_a_copy_stays_its_holders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "x.lock"
    lock = LockFile(path)
    assert lock.acquire() is True
    first = lock.read()

    def refuse(source, target):
        raise PermissionError(errno.EPERM, "Incorrect function")

    monkeypatch.setattr(filesystem, "os", PatchedOs(link=refuse))
    judge = LockFile(path)
    judge._put_back(judge._move_aside())
    assert LockFile(path).read() == first

    assert lock.still_held() is True
    time.sleep(0.01)
    lock.renew()
    assert LockFile(path).read().created > first.created
    assert LockFile(path, wait_s=0.0).acquire() is False
    lock.release()
    assert list(tmp_path.iterdir()) == []


def test_two_takes_of_one_lock_carry_two_tokens(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    first = LockFile(path)
    assert first.acquire() is True
    token = first.read().token
    first.release()
    second = LockFile(path)
    assert second.acquire() is True
    assert len(token) == 32 and second.read().token not in ("", token)
    assert first.still_held() is False


@pytest.mark.parametrize("operation", ["replace", "unlink"])
def test_a_refused_release_off_windows_raises_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    waited: list[float] = []
    monkeypatch.setattr(filesystem.time, "sleep", waited.append)
    path = tmp_path / "x.lock"
    lock = LockFile(path)
    assert lock.acquire() is True
    patched = PatchedOs(name="posix", **{operation: _in_use(1, getattr(os, operation))})
    monkeypatch.setattr(filesystem, "os", patched)

    with pytest.raises(PermissionError):
        lock.release()
    assert waited == []


@pytest.mark.skipif(os.name != "nt", reason="the real Windows kernel only")
def test_windows_renews_and_releases_while_a_reader_holds_the_lock(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    lock = LockFile(path)
    assert lock.acquire() is True
    first = lock.read().created

    with open(path, "rb"):
        time.sleep(0.02)
        lock.renew()
    assert lock.read().created > first

    reader = open(path, "rb")  # noqa: SIM115 - closed by the timer while release retries
    closer = threading.Timer(0.05, reader.close)
    closer.start()
    try:
        lock.release()
    finally:
        closer.join()
        reader.close()
    assert not path.exists()
