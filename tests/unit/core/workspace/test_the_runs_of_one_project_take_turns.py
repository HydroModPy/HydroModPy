"""The runs of one project take turns; the runs of two projects do not wait on each other."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from hydromodpy.core.workspace import path_registry
from hydromodpy.core.workspace.path_registry import (
    holds_project_run_lock,
    project_root_of_config,
    project_run_lock,
)

pytestmark = pytest.mark.unit


def _hold_in_another_process(project_root: Path, seconds: float) -> subprocess.Popen:
    script = textwrap.dedent(
        f"""
        import sys, time
        from pathlib import Path
        from hydromodpy.core.workspace.path_registry import project_run_lock
        with project_run_lock(Path({str(project_root)!r})):
            print("held", flush=True)
            time.sleep({seconds})
        """
    )
    proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "held"
    return proc


@pytest.mark.allow_subprocess
def test_a_second_run_of_the_project_waits_for_the_first(tmp_path: Path) -> None:
    proc = _hold_in_another_process(tmp_path, 1.5)
    try:
        start = time.monotonic()
        with project_run_lock(tmp_path):
            waited = time.monotonic() - start
    finally:
        proc.wait(timeout=30)

    assert waited > 0.8


@pytest.mark.allow_subprocess
def test_another_project_does_not_wait(tmp_path: Path) -> None:
    proc = _hold_in_another_process(tmp_path / "a", 1.5)
    try:
        start = time.monotonic()
        with project_run_lock(tmp_path / "b"):
            waited = time.monotonic() - start
    finally:
        proc.wait(timeout=30)

    assert waited < 0.8


def test_the_lock_is_reentrant_across_threads_of_one_process(tmp_path: Path) -> None:
    done = threading.Event()

    def trial() -> None:
        with project_run_lock(tmp_path):
            done.set()

    with project_run_lock(tmp_path):
        with project_run_lock(tmp_path):
            worker = threading.Thread(target=trial)
            worker.start()
            worker.join(timeout=5)
        assert done.is_set()
        assert str(tmp_path.resolve()) in path_registry._RUN_LOCKS
    assert str(tmp_path.resolve()) not in path_registry._RUN_LOCKS


def test_the_decorator_holds_the_lock_during_the_call(tmp_path: Path) -> None:
    seen: list[bool] = []

    @holds_project_run_lock(lambda root: root)
    def calibrate(root: Path) -> str:
        seen.append(str(root.resolve()) in path_registry._RUN_LOCKS)
        return "done"

    assert calibrate(tmp_path) == "done"
    assert seen == [True]
    assert str(tmp_path.resolve()) not in path_registry._RUN_LOCKS


def test_the_project_root_of_a_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HMP_PROJECT_ROOT", raising=False)
    base = tmp_path / "base.toml"
    base.write_text('[workspace]\nproject_root = "proj"\n', encoding="utf-8")
    leaf = tmp_path / "leaf.toml"
    leaf.write_text('base_config = "base.toml"\n', encoding="utf-8")
    bare = tmp_path / "bare.toml"
    bare.write_text("[simulation]\nname = 'x'\n", encoding="utf-8")

    assert project_root_of_config(leaf) == (tmp_path / "proj").resolve()
    assert project_root_of_config(bare) == tmp_path.resolve()
    assert project_root_of_config(bare, workspace=tmp_path / "w") == (tmp_path / "w").resolve()
    monkeypatch.setenv("HMP_PROJECT_ROOT", str(tmp_path / "env"))
    assert project_root_of_config(leaf) == (tmp_path / "env").resolve()
