"""The lease of the launcher: ``.hmp/launcher.lease`` taken with O_EXCL, one launcher per project.

A second launcher is refused with the host and the process that hold the
lease. A lease left by a dead process of this host is taken over; a lease of
another host, or of a live process, only with ``force``. A launcher releases
only the lease it wrote.
"""

from __future__ import annotations

import json
import os
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.cli.helpers import EXIT_WRITE_CONFLICT, exit_code_for
from hydromodpy.project.launch import local as launch_local
from hydromodpy.project.launch.lease import (
    LeaseHeldError,
    acquire_lease,
    launcher_lease,
    lease_path,
    read_lease,
    release_lease,
)


def _write_lease(project: Path, *, host: str, pid: int) -> Path:
    path = lease_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"host": host, "pid": pid, "started_at": datetime.now(UTC).isoformat()}),
        encoding="utf-8",
    )
    return path


def _dead_pid() -> int:
    pid = 4_000_000
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return pid
        except PermissionError:
            pass
        pid += 1


def test_the_lease_names_its_host_and_process_and_a_second_launcher_is_refused(
    tmp_path: Path,
) -> None:
    lease = acquire_lease(tmp_path)

    held = read_lease(tmp_path)
    assert held is not None
    assert (held.host, held.pid) == (socket.gethostname(), os.getpid())
    assert lease.path == tmp_path / ".hmp" / "launcher.lease"
    with pytest.raises(LeaseHeldError) as refused:
        acquire_lease(tmp_path)
    assert f"pid {os.getpid()}" in str(refused.value)
    assert socket.gethostname() in str(refused.value)
    assert exit_code_for(refused.value) == EXIT_WRITE_CONFLICT

    release_lease(lease)
    assert not lease.path.exists()


def test_a_lease_of_a_dead_process_of_this_host_is_taken_over(tmp_path: Path) -> None:
    _write_lease(tmp_path, host=socket.gethostname(), pid=_dead_pid())

    lease = acquire_lease(tmp_path)

    assert lease.pid == os.getpid()
    held = read_lease(tmp_path)
    assert held is not None and held.pid == os.getpid()


def test_a_lease_of_another_host_is_taken_only_by_force(tmp_path: Path) -> None:
    _write_lease(tmp_path, host="node-042.cluster", pid=1234)

    with pytest.raises(LeaseHeldError, match="node-042.cluster"):
        acquire_lease(tmp_path)
    lease = acquire_lease(tmp_path, force=True)

    assert lease.host == socket.gethostname()


def test_a_launcher_releases_only_the_lease_it_wrote(tmp_path: Path) -> None:
    with launcher_lease(tmp_path) as lease:
        _write_lease(tmp_path, host="node-042.cluster", pid=1234)
        assert lease.path.is_file()

    held = read_lease(tmp_path)
    assert held is not None and held.host == "node-042.cluster"


def test_run_plan_refuses_a_project_another_launcher_holds(tmp_path: Path) -> None:
    project = tmp_path / "campaign"
    project.mkdir()
    (project / "project.toml").write_text(
        '[sites]\ntable = "sites.csv"\n[sites.recipes]\nbase = "project.toml"\n', encoding="utf-8"
    )
    _write_lease(project, host="node-042.cluster", pid=1234)

    with pytest.raises(LeaseHeldError, match="node-042.cluster"):
        launch_local.run_plan(project)
    assert not (project / "jobs").exists()
