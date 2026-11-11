"""The logs of an attempt: its own run.log, the project log, the rotation, the tail."""

from __future__ import annotations

import re
import threading
from pathlib import Path

import pytest

from hydromodpy.core.logging import RUN_SINKS, get_logger
from hydromodpy.results.storage import run_log
from hydromodpy.results.storage.run_log import (
    attach_run_log,
    detach_run_log,
    in_project_log,
    project_log,
    project_log_path,
    read_log_tail,
    rotate_project_log,
    run_log_path,
)

LOGGER = get_logger("hydromodpy.tests.run_log")


def _run_dir(project: Path, name: str) -> Path:
    folder = project / "runs" / name
    folder.mkdir(parents=True)
    return folder


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _attempt(project: Path, name: str, count: int, ready: threading.Barrier) -> None:
    """Play the log of one attempt in the context of the calling thread."""
    logs = attach_run_log(_run_dir(project, name), project)
    try:
        ready.wait(timeout=30)
        for index in range(count):
            LOGGER.debug("%s %d", name, index)
        ready.wait(timeout=30)
    finally:
        detach_run_log(logs)


def test_an_attempt_writes_debug_lines_to_its_run_log_and_to_the_project_log(
    tmp_path: Path,
) -> None:
    run = _run_dir(tmp_path, "basin")
    logs = attach_run_log(run, tmp_path)
    try:
        LOGGER.debug("a debug line")
        LOGGER.warning("a warning")
    finally:
        detach_run_log(logs)

    pattern = re.compile(
        r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} \[DEBUG\] \[hydromodpy\.tests\.run_log\] "
        r"\[test_run_log:\d+\] a debug line$"
    )
    for path in (run_log_path(run), project_log_path(tmp_path)):
        lines = _lines(path)
        assert len(lines) == 2
        assert pattern.match(lines[0])
        assert "[WARNING]" in lines[1]
    assert run_log_path(run) == run / "logs" / "run.log"
    assert project_log_path(tmp_path) == tmp_path / ".hmp" / "logs" / "hydromodpy_debug.log"


def test_without_a_project_only_the_run_log_is_written(tmp_path: Path) -> None:
    run = _run_dir(tmp_path, "basin")
    logs = attach_run_log(run)
    try:
        LOGGER.debug("alone")
    finally:
        detach_run_log(logs)

    assert _lines(run_log_path(run))[0].endswith("alone")
    assert not (tmp_path / ".hmp").exists()


def test_detaching_gives_the_sinks_back_and_closes_the_files(tmp_path: Path) -> None:
    outer = attach_run_log(_run_dir(tmp_path, "outer"), tmp_path)
    inner = attach_run_log(_run_dir(tmp_path, "inner"), tmp_path)
    assert RUN_SINKS.get() == outer.handlers + inner.handlers

    detach_run_log(inner)
    assert RUN_SINKS.get() == outer.handlers
    assert all(handler.stream is None for handler in inner.handlers)

    detach_run_log(outer)
    assert RUN_SINKS.get() == ()


def test_a_block_writes_the_project_log_and_an_attempt_inside_it_adds_its_run_log(
    tmp_path: Path,
) -> None:
    with project_log(tmp_path):
        LOGGER.debug("before the run")
        logs = attach_run_log(_run_dir(tmp_path, "cycle"), tmp_path)
        assert len(logs.handlers) == 1
        LOGGER.debug("inside the run")
        detach_run_log(logs)
        LOGGER.debug("after the run")
    assert RUN_SINKS.get() == ()
    LOGGER.debug("outside the block")

    lines = _lines(project_log_path(tmp_path))
    assert [line.rsplit("] ", 1)[1] for line in lines] == [
        "before the run",
        "inside the run",
        "after the run",
    ]
    assert len(_lines(run_log_path(tmp_path / "runs" / "cycle"))) == 1


def test_a_decorated_call_writes_the_project_log_of_the_root_it_names(tmp_path: Path) -> None:
    @in_project_log(lambda root, **_kw: root)
    def call(root: Path) -> str:
        LOGGER.debug("in the call")
        return "done"

    assert call(tmp_path) == "done"
    assert RUN_SINKS.get() == ()
    assert _lines(project_log_path(tmp_path))[0].endswith("in the call")


def test_two_attempts_in_two_threads_write_two_run_logs_and_share_the_project_log(
    tmp_path: Path,
) -> None:
    ready = threading.Barrier(2)
    threads = [
        threading.Thread(target=_attempt, args=(tmp_path, name, 200, ready))
        for name in ("alpha", "beta")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    for name in ("alpha", "beta"):
        own = _lines(run_log_path(tmp_path / "runs" / name))
        assert [line.rsplit("] ", 1)[1] for line in own] == [f"{name} {i}" for i in range(200)]
    shared = [line.rsplit("] ", 1)[1] for line in _lines(project_log_path(tmp_path))]
    assert sorted(shared) == sorted(f"{name} {i}" for name in ("alpha", "beta") for i in range(200))


@pytest.mark.parametrize(
    ("kept_before", "size", "kept_after"),
    [
        pytest.param((), 5, (), id="a small log stays"),
        pytest.param((), 11, (1,), id="a big log becomes .1"),
        pytest.param((1,), 11, (1, 2), id="the old .1 becomes .2"),
        pytest.param((1, 2, 3), 11, (1, 2, 3), id="the oldest one is dropped"),
    ],
)
def test_the_project_log_rotates_when_it_is_past_the_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kept_before: tuple[int, ...],
    size: int,
    kept_after: tuple[int, ...],
) -> None:
    monkeypatch.setattr(run_log, "PROJECT_LOG_MAX_BYTES", 10)
    path = project_log_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("x" * size, encoding="utf-8")
    for index in kept_before:
        path.with_name(f"{path.name}.{index}").write_text(f"old {index}", encoding="utf-8")

    rotate_project_log(path)

    kept = sorted(
        int(entry.suffix[1:]) for entry in path.parent.iterdir() if entry.suffix[1:].isdigit()
    )
    assert tuple(kept) == kept_after
    assert path.exists() == (size <= 10)
    if size > 10:
        assert path.with_name(f"{path.name}.1").read_text() == "x" * size
    if 2 in kept_after and size > 10:
        assert path.with_name(f"{path.name}.2").read_text() == "old 1"
    if (1, 2, 3) == kept_before:
        assert path.with_name(f"{path.name}.3").read_text() == "old 2"


def test_a_missing_project_log_is_not_rotated(tmp_path: Path) -> None:
    rotate_project_log(project_log_path(tmp_path))

    assert not (tmp_path / ".hmp").exists()


def test_a_rename_that_fails_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_log, "PROJECT_LOG_MAX_BYTES", 10)
    path = project_log_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("x" * 11, encoding="utf-8")

    def another_run_did_it(source: object, target: object) -> None:
        raise PermissionError("held by another run")

    monkeypatch.setattr(run_log.os, "replace", another_run_did_it)
    rotate_project_log(path)

    assert path.read_text() == "x" * 11


def test_an_attempt_opens_the_project_log_after_its_rotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_log, "PROJECT_LOG_MAX_BYTES", 10)
    path = project_log_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("x" * 11, encoding="utf-8")

    logs = attach_run_log(_run_dir(tmp_path, "basin"), tmp_path)
    try:
        LOGGER.debug("fresh")
    finally:
        detach_run_log(logs)

    assert path.with_name(f"{path.name}.1").read_text() == "x" * 11
    assert len(_lines(path)) == 1


def test_a_project_log_that_cannot_be_opened_leaves_the_run_log(tmp_path: Path) -> None:
    (tmp_path / ".hmp").write_text("a file where the folder should be", encoding="utf-8")
    run = _run_dir(tmp_path, "basin")

    logs = attach_run_log(run, tmp_path)
    try:
        LOGGER.debug("still written")
    finally:
        detach_run_log(logs)

    assert len(logs.handlers) == 1
    assert _lines(run_log_path(run))[0].endswith("still written")


def test_the_tail_is_the_last_lines_of_the_run_log(tmp_path: Path) -> None:
    run = _run_dir(tmp_path, "basin")
    assert read_log_tail(run) == []

    path = run_log_path(run)
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(f"line {index}" for index in range(30)) + "\n", encoding="utf-8")

    assert read_log_tail(run, 3) == ["line 27", "line 28", "line 29"]
    assert len(read_log_tail(run)) == run_log.LOG_TAIL_LINES
