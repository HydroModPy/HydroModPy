"""The lease of the launcher: ``.hmp/launcher.lease`` taken with O_EXCL, one launcher per project.

A second launcher is refused with the host and the process that hold the
lease. A lease left by a dead process of this host is taken over; a lease of
another host, or of a live process, only with ``force``. A launcher releases
only the lease it wrote.

Two launchers taking over the lease of a dead one never both hold the project.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.cli.helpers import EXIT_WRITE_CONFLICT, exit_code_for
from hydromodpy.core.state import host as host_module
from hydromodpy.core.state.host import host_name
from hydromodpy.project.launch import lease as lease_module
from hydromodpy.project.launch import local as launch_local
from hydromodpy.project.launch.lease import (
    LEASE_SCHEMA,
    LeaseHeldError,
    acquire_lease,
    launcher_lease,
    lease_path,
    read_lease,
    release_lease,
)
from tests.unit.project.launch._helpers import dead_pid


def _write_lease(project: Path, *, host: str, pid: int) -> Path:
    path = lease_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": LEASE_SCHEMA,
                "host": host,
                "pid": pid,
                "started_at": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    return path


def test_the_lease_names_its_host_and_process_and_a_second_launcher_is_refused(
    tmp_path: Path,
) -> None:
    lease = acquire_lease(tmp_path)

    held = read_lease(tmp_path)
    assert held is not None
    assert (held.host, held.pid) == (host_name(), os.getpid())
    assert lease.path == tmp_path / ".hmp" / "launcher.lease"
    with pytest.raises(LeaseHeldError) as refused:
        acquire_lease(tmp_path)
    assert f"pid {os.getpid()}" in str(refused.value)
    assert host_name() in str(refused.value)
    assert exit_code_for(refused.value) == EXIT_WRITE_CONFLICT

    release_lease(lease)
    assert not lease.path.exists()


def test_a_lease_of_a_dead_process_of_this_host_is_taken_over(tmp_path: Path) -> None:
    _write_lease(tmp_path, host=host_name(), pid=dead_pid())

    lease = acquire_lease(tmp_path)

    assert lease.pid == os.getpid()
    held = read_lease(tmp_path)
    assert held is not None and held.pid == os.getpid()


def test_a_lease_of_another_host_is_taken_only_by_force(tmp_path: Path) -> None:
    _write_lease(tmp_path, host="node-042.cluster", pid=1234)

    with pytest.raises(LeaseHeldError, match="node-042.cluster"):
        acquire_lease(tmp_path)
    lease = acquire_lease(tmp_path, force=True)

    assert lease.host == host_name()


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


DEAD_PID = 424242


def test_two_launchers_never_both_take_over_a_dead_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = lease_module.lease_path(tmp_path)
    path.parent.mkdir(parents=True)
    stale = {"schema": lease_module.LEASE_SCHEMA, "host": host_name(), "pid": DEAD_PID}
    path.write_text(json.dumps({**stale, "started_at": "2026-10-16T00:00:00+00:00"}))
    judged = lease_module.read_lease(tmp_path)
    assert judged is not None
    # Launcher A takes the dead lease over before launcher B removes it.
    fresh = lease_module.Lease(path, host_name(), os.getpid(), datetime.now(UTC))
    path.write_text(json.dumps(fresh.to_document()))

    with pytest.raises(lease_module.LeaseHeldError, match=f"pid {os.getpid()}"):
        lease_module._take_over(path, judged)

    held = lease_module.read_lease(tmp_path)
    assert held is not None and held.pid == os.getpid()
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]


def test_a_dead_lease_is_taken_over(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_module, "process_is_alive", lambda pid: pid != DEAD_PID)
    path = lease_module.lease_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema": lease_module.LEASE_SCHEMA,
                "host": host_name(),
                "pid": DEAD_PID,
                "started_at": "2026-10-16T00:00:00+00:00",
            }
        )
    )

    with lease_module.launcher_lease(tmp_path) as lease:
        assert lease.pid == os.getpid()

    assert not path.exists()


def test_a_lease_put_back_when_os_link_is_refused_is_copied_and_the_takeover_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = lease_path(tmp_path)
    path.parent.mkdir(parents=True)
    judged = lease_module.Lease(path, host_name(), DEAD_PID, datetime.now(UTC))
    path.write_text(json.dumps(judged.to_document()))
    other = lease_module.Lease(path, "elsewhere", 7, datetime.now(UTC))
    # A fresh launcher answers between the read and the move aside.
    path.write_text(json.dumps(other.to_document()))

    def refused(source: object, target: object) -> None:
        raise PermissionError("no hard link here")

    monkeypatch.setattr(os, "link", refused)
    with pytest.raises(LeaseHeldError, match="elsewhere"):
        lease_module._take_over(path, judged)

    held = read_lease(tmp_path)
    assert held is not None and (held.host, held.pid) == ("elsewhere", 7)
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]


def test_a_lease_present_is_never_overwritten_by_the_put_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = lease_path(tmp_path)
    path.parent.mkdir(parents=True)
    judged = lease_module.Lease(path, host_name(), DEAD_PID, datetime.now(UTC))
    path.write_text(json.dumps(other_doc := {**judged.to_document(), "pid": 8, "host": "a"}))
    original_move = os.replace

    def third_launcher_writes(source: Path, target: Path) -> None:
        original_move(source, target)
        path.write_text(json.dumps({**other_doc, "pid": 9}))

    monkeypatch.setattr(os, "replace", third_launcher_writes)
    monkeypatch.setattr(os, "link", lambda *_: (_ for _ in ()).throw(PermissionError("no link")))
    with pytest.raises(LeaseHeldError):
        lease_module._take_over(path, judged)

    held = read_lease(tmp_path)
    assert held is not None and held.pid == 9


def test_a_windows_takeover_retries_the_move_and_a_kept_aside_file_hides_no_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    from hydromodpy.core.io import filesystem
    from tests._helpers.windows_os import PatchedOs, WindowsOs

    path = lease_path(tmp_path)
    path.parent.mkdir(parents=True)
    judged = lease_module.Lease(path, host_name(), DEAD_PID, datetime.now(UTC))
    other = lease_module.Lease(path, "elsewhere", 7, datetime.now(UTC))
    path.write_text(json.dumps(other.to_document()))
    refusals = [2]

    def replace_once_free(source: object, target: object) -> None:
        if refusals[0]:
            refusals[0] -= 1
            raise PermissionError(errno.EACCES, "The file is used by another process")
        os.replace(source, target)

    def unlink_never(path: object) -> None:
        raise PermissionError(errno.EACCES, "The file is used by another process")

    patched = PatchedOs(name="nt", replace=replace_once_free, unlink=unlink_never)
    monkeypatch.setattr(filesystem, "os", patched)
    monkeypatch.setattr(filesystem.time, "sleep", lambda _s: None)
    monkeypatch.setattr(lease_module, "os", WindowsOs())

    with pytest.raises(LeaseHeldError, match="elsewhere"):
        lease_module._take_over(path, judged)

    assert refusals == [0]
    held = read_lease(tmp_path)
    assert held is not None and (held.host, held.pid) == ("elsewhere", 7)
