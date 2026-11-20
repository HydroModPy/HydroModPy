"""What only a second process on the real kernel shows: open files, dead locks, process trees.

Each case runs on Linux and on Windows. The assertion that depends on the
kernel is written once per platform. A process id is judged alive by
``alive_here``, never by ``os.kill(pid, 0)``, which sends a Ctrl+C event on Windows.
"""

from __future__ import annotations

import multiprocessing
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hydromodpy.calibration.runners import worker_pool
from hydromodpy.core.exceptions import WriteConflictError
from hydromodpy.core.io.atomic_replace import rename_over_open_file
from hydromodpy.core.io.lock_file import LockFile
from hydromodpy.core.state.host import alive_here, death_is_proven, host_name
from hydromodpy.results.catalog.index_file import index_lock, index_lock_path

ON_WINDOWS = os.name == "nt"
SPAWN = multiprocessing.get_context("spawn")
WAIT_S = 120.0


def _hold_a_file_open(target: str, report: str, ready, stop) -> None:
    """Child: read one byte of ``target``, wait, then report every byte read after the wait."""
    with open(target, "rb") as handle:
        handle.read(1)
        ready.set()
        stop.wait(WAIT_S)
        Path(report).write_text(",".join(sorted({str(b) for b in handle.read()})))


def test_a_publish_over_a_file_held_open_leaves_old_or_new_never_a_mix(tmp_path: Path) -> None:
    target, source, report = tmp_path / "doc.bin", tmp_path / "doc.new", tmp_path / "report"
    old, new = b"o" * 4096, b"n" * 4096
    target.write_bytes(old)
    source.write_bytes(new)
    ready, stop = SPAWN.Event(), SPAWN.Event()
    reader = SPAWN.Process(target=_hold_a_file_open, args=(str(target), str(report), ready, stop))
    reader.start()
    try:
        assert ready.wait(WAIT_S)
        refused: OSError | None = None
        try:
            rename_over_open_file(source, target)
        except OSError as error:
            refused = error
    finally:
        stop.set()
        reader.join(WAIT_S)

    assert reader.exitcode == 0
    assert target.read_bytes() in (old, new)
    if refused is None:
        assert target.read_bytes() == new
        assert not source.exists()
    else:
        assert ON_WINDOWS, f"POSIX renames over an open file, and refused with {refused!r}"
        assert target.read_bytes() == old
        assert source.read_bytes() == new
    # The open handle keeps the bytes it opened, whichever way the publish went.
    assert report.read_text() == str(old[0])


def _hold_the_index(project: str, ready, stop) -> None:
    with index_lock(project):
        ready.set()
        stop.wait(WAIT_S)


def _wait_gone(pid: int, within_s: float) -> bool:
    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        if not alive_here(host_name(), pid):
            return True
        time.sleep(0.05)
    return not alive_here(host_name(), pid)


def test_the_index_lock_of_a_killed_process_is_taken_back_and_a_live_one_never(
    tmp_path: Path,
) -> None:
    ready, stop = SPAWN.Event(), SPAWN.Event()
    holder = SPAWN.Process(target=_hold_the_index, args=(str(tmp_path), ready, stop))
    holder.start()
    try:
        assert ready.wait(WAIT_S)
        info = LockFile(index_lock_path(tmp_path)).read()
        assert info is not None
        assert info.pid == holder.pid
        assert alive_here(info.host, info.pid)
        assert not death_is_proven(info.host, info.pid)

        with pytest.raises(WriteConflictError, match=str(holder.pid)):
            with index_lock(tmp_path, wait_s=0.3):
                pytest.fail("the lock of a live process was taken")
        assert LockFile(index_lock_path(tmp_path)).read() == info

        holder.kill()
        holder.join(WAIT_S)
    finally:
        holder.kill()
        holder.join(WAIT_S)

    assert death_is_proven(info.host, info.pid)
    with index_lock(tmp_path, wait_s=30.0) as lock:
        taken = lock.read()
        assert taken is not None
        assert taken.pid == os.getpid()


_GRANDCHILD = "import time; time.sleep(600)"


def _start_a_tree(pid_file: str) -> None:
    """Child: lead a group of its own as a pool worker does, start a grandchild, then wait."""
    if not ON_WINDOWS:
        os.setsid()
    grandchild = subprocess.Popen([sys.executable, "-c", _GRANDCHILD])
    Path(pid_file).write_text(str(grandchild.pid))
    time.sleep(600)


def test_ending_a_worker_group_ends_the_process_it_started(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    worker = SPAWN.Process(target=_start_a_tree, args=(str(pid_file),))
    worker.start()
    grandchild = 0
    try:
        deadline = time.monotonic() + WAIT_S
        while time.monotonic() < deadline and not (pid_file.exists() and pid_file.read_text()):
            time.sleep(0.05)
        grandchild = int(pid_file.read_text())
        assert alive_here(host_name(), worker.pid)
        assert alive_here(host_name(), grandchild)

        worker_pool._end_group(worker.pid)
        worker.join(WAIT_S)
        assert _wait_gone(grandchild, 5.0), "the grandchild outlived its worker"
    finally:
        worker.kill()
        worker.join(WAIT_S)
        if grandchild and alive_here(host_name(), grandchild):
            if ON_WINDOWS:
                subprocess.run(["taskkill", "/F", "/PID", str(grandchild)], check=False)
            else:
                os.kill(grandchild, signal.SIGKILL)
