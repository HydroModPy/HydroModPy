"""The filesystem helpers: sizes, the project root bound, links, renames, removals."""

from __future__ import annotations

import errno
import os
import time
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.io import filesystem
from hydromodpy.core.io.filesystem import (
    check_project_root,
    link_or_copy,
    native_io_path,
    path_size,
    rename_onto_empty_dir,
    replace_when_free,
    unlink_when_free,
)
from tests._helpers.windows_os import PatchedOs, WindowsOs


def test_the_size_of_a_file_is_its_bytes(tmp_path: Path) -> None:
    file = tmp_path / "a.bin"
    file.write_bytes(b"12345")
    assert path_size(file) == 5


def test_the_size_of_a_folder_sums_its_files_and_skips_its_folders(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.bin").write_bytes(b"123")
    (tmp_path / "sub" / "b.bin").write_bytes(b"4567")
    assert path_size(tmp_path) == 7


def test_a_path_that_is_gone_weighs_nothing(tmp_path: Path) -> None:
    assert path_size(tmp_path / "missing") == 0


def test_a_file_removed_during_the_walk_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "kept.bin").write_bytes(b"12")
    gone = tmp_path / "gone.bin"
    gone.write_bytes(b"345")
    is_file = Path.is_file

    def racing_is_file(self: Path) -> bool:
        if self == gone:
            raise OSError("removed while walked")
        return is_file(self)

    monkeypatch.setattr(Path, "is_file", racing_is_file)
    assert path_size(tmp_path) == 2


# --- The Windows bounds: project root, link, rename onto a reservation, retried removal.


def _absolute_path_of(length: int) -> str:
    """An absolute POSIX path of exactly ``length`` characters."""
    return "/" + "a" * (length - 1)


def _refusal(path: str) -> str:
    return (
        f"The project folder {path} is {len(path)} characters long. On Windows a project "
        "writes paths up to 160 characters below its folder, and MODFLOW 6 and DuckDB open "
        "no path longer than 259, so the folder may hold 99 characters at most. Move the "
        "project to a shorter folder, for example D:\\hmp\\<organisation>\\projects\\<name>."
    )


def test_the_budget_constants() -> None:
    assert filesystem.WINDOWS_PATH_LIMIT == 259
    assert filesystem.PROJECT_TREE_DEPTH == 160


@pytest.mark.skipif(os.name == "nt", reason="the root is built as a POSIX path")
@pytest.mark.parametrize(
    ("length", "windows", "refused"),
    [(98, True, False), (99, True, False), (100, True, True), (300, False, False)],
    ids=["98-windows", "99-windows", "100-windows", "300-linux"],
)
def test_a_project_root_is_bounded_on_windows_only(length, windows, refused) -> None:
    root = _absolute_path_of(length)
    if not refused:
        check_project_root(root, windows=windows)
        return
    with pytest.raises(ConfigError) as caught:
        check_project_root(root, windows=windows)
    assert str(caught.value) == _refusal(root)


@pytest.mark.skipif(os.name == "nt", reason="the root is built as a POSIX path")
@pytest.mark.parametrize(("windows_os", "refused"), [(True, True), (False, False)])
def test_the_default_follows_os_name_at_the_call(
    monkeypatch: pytest.MonkeyPatch, windows_os: bool, refused: bool
) -> None:
    if windows_os:
        monkeypatch.setattr(filesystem, "os", WindowsOs())
    root = _absolute_path_of(120)
    if refused:
        with pytest.raises(ConfigError, match="120 characters long"):
            check_project_root(root)
    else:
        check_project_root(root)


def test_a_link_shares_the_file(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"lock")
    target = tmp_path / "target.bin"
    assert link_or_copy(source, target) is True
    assert os.path.samefile(source, target)


@pytest.mark.parametrize(
    "refusal",
    [
        OSError(errno.EXDEV, "Invalid cross-device link"),
        PermissionError(errno.EPERM, "Incorrect function"),
        OSError(errno.ENOTSUP, "Operation not supported"),
    ],
    ids=["other-volume", "windows-permission", "no-links"],
)
def test_a_refused_link_copies_the_same_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refusal: OSError
) -> None:
    def refuse(source, target):
        raise refusal

    monkeypatch.setattr(filesystem, "os", PatchedOs(link=refuse))
    source = tmp_path / "source.bin"
    source.write_bytes(b"\x00\x01binary\r\n")
    source.chmod(0o755)
    target = tmp_path / "target.bin"
    assert link_or_copy(source, target) is False
    assert target.read_bytes() == b"\x00\x01binary\r\n"
    assert not os.path.samefile(source, target)
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize("link_refused", [False, True], ids=["link", "copy"])
def test_a_present_target_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, link_refused: bool
) -> None:
    if link_refused:

        def refuse(source, target):
            raise PermissionError(errno.EPERM, "Incorrect function")

        monkeypatch.setattr(filesystem, "os", PatchedOs(link=refuse))
    source = tmp_path / "source.bin"
    source.write_bytes(b"new")
    target = tmp_path / "target.bin"
    target.write_bytes(b"held")
    with pytest.raises(FileExistsError):
        link_or_copy(source, target)
    assert target.read_bytes() == b"held"


def test_a_missing_source_leaves_no_target(tmp_path: Path) -> None:
    target = tmp_path / "target.bin"
    with pytest.raises(FileNotFoundError):
        link_or_copy(tmp_path / "missing.bin", target)
    assert not target.exists()


def _trial(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "kept"
    source.mkdir()
    (source / "result.json").write_text("{}", encoding="utf-8")
    reserved = tmp_path / "trial_0001"
    reserved.mkdir()
    return source, reserved


def _windows_replace(source, target):
    if os.path.isdir(target):
        raise PermissionError(errno.EACCES, "Access is denied", str(target))
    return os.replace(source, target)


@pytest.mark.skipif(os.name == "nt", reason="POSIX renames onto an empty folder in one step")
def test_posix_renames_onto_the_reserved_folder_in_one_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_rmdir(path):
        raise AssertionError("the reserved folder is replaced, never removed")

    monkeypatch.setattr(filesystem, "os", PatchedOs(rmdir=no_rmdir))
    source, reserved = _trial(tmp_path)
    rename_onto_empty_dir(source, reserved)
    assert (reserved / "result.json").read_text(encoding="utf-8") == "{}"
    assert not source.exists()


def test_a_refused_replace_removes_the_reservation_then_renames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(filesystem, "os", PatchedOs(name="nt", replace=_windows_replace))
    source, reserved = _trial(tmp_path)
    rename_onto_empty_dir(source, reserved)
    assert (reserved / "result.json").read_text(encoding="utf-8") == "{}"
    assert not source.exists()


def test_a_name_taken_between_the_two_steps_raises_and_stays_its_owners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def rmdir_then_taken(path):
        os.rmdir(path)
        os.mkdir(path)
        (Path(path) / "other.json").write_text("other", encoding="utf-8")

    patched = PatchedOs(name="nt", replace=_windows_replace, rmdir=rmdir_then_taken)
    monkeypatch.setattr(filesystem, "os", patched)
    source, reserved = _trial(tmp_path)
    with pytest.raises(FileExistsError):
        rename_onto_empty_dir(source, reserved)
    assert (reserved / "other.json").read_text(encoding="utf-8") == "other"
    assert (source / "result.json").exists()


def test_a_reservation_that_is_not_empty_raises_without_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(filesystem, "os", PatchedOs(name="nt", replace=_windows_replace))
    source, reserved = _trial(tmp_path)
    (reserved / "other.json").write_text("other", encoding="utf-8")
    with pytest.raises(PermissionError):
        rename_onto_empty_dir(source, reserved)
    assert (reserved / "other.json").read_text(encoding="utf-8") == "other"
    assert (source / "result.json").exists()


def _flaky(failures: int, then):
    """A function that raises ``PermissionError`` ``failures`` times, then calls ``then``."""
    calls: list[tuple] = []

    def call(*args):
        calls.append(args)
        if len(calls) <= failures:
            raise PermissionError(errno.EACCES, "The file is used by another process")
        return then(*args)

    return call, calls


@pytest.mark.parametrize(
    ("failures", "raises", "sleeps"),
    [
        (0, False, []),
        (2, False, [0.01, 0.02]),
        (6, True, [0.01, 0.02, 0.04, 0.08, 0.16]),
    ],
    ids=["free", "two-refusals", "six-refusals"],
)
@pytest.mark.parametrize("operation", ["unlink", "replace"])
def test_a_file_in_use_is_retried_six_times_for_310_ms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    failures: int,
    raises: bool,
    sleeps: list[float],
) -> None:
    waited: list[float] = []
    monkeypatch.setattr(filesystem.time, "sleep", waited.append)
    path = tmp_path / "x.lock"
    path.write_bytes(b"{}")
    moved = tmp_path / "x.lock.aside"
    flaky, calls = _flaky(failures, getattr(os, operation))
    monkeypatch.setattr(filesystem, "os", PatchedOs(name="nt", **{operation: flaky}))

    def act() -> None:
        if operation == "unlink":
            unlink_when_free(path)
        else:
            replace_when_free(path, moved)

    if raises:
        with pytest.raises(PermissionError):
            act()
        assert path.exists()
    else:
        act()
        assert not path.exists()
        assert moved.exists() == (operation == "replace")
    assert len(calls) == min(failures + 1, 6)
    assert waited == pytest.approx(sleeps)
    assert sum(waited) == pytest.approx(0.31 if raises else sum(sleeps))


def test_a_windows_second_step_refused_twice_still_moves_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waited: list[float] = []
    monkeypatch.setattr(filesystem.time, "sleep", waited.append)
    flaky, calls = _flaky(2, os.rename)
    patched = PatchedOs(name="nt", replace=_windows_replace, rename=flaky)
    monkeypatch.setattr(filesystem, "os", patched)
    source, reserved = _trial(tmp_path)
    rename_onto_empty_dir(source, reserved)
    assert (reserved / "result.json").read_text(encoding="utf-8") == "{}"
    assert len(calls) == 3
    assert waited == pytest.approx([0.01, 0.02])


@pytest.mark.parametrize("operation", ["unlink", "replace", "folder"])
def test_off_windows_a_refusal_is_raised_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    waited: list[float] = []
    monkeypatch.setattr(filesystem.time, "sleep", waited.append)
    path = tmp_path / "x.lock"
    path.write_bytes(b"{}")
    source, reserved = _trial(tmp_path)
    name = "replace" if operation == "folder" else operation
    flaky, calls = _flaky(10**6, getattr(os, name))
    monkeypatch.setattr(filesystem, "os", PatchedOs(name="posix", **{name: flaky}))
    started = time.monotonic()
    with pytest.raises(PermissionError):
        if operation == "unlink":
            unlink_when_free(path)
        elif operation == "replace":
            replace_when_free(path, tmp_path / "aside")
        else:
            rename_onto_empty_dir(source, reserved)
    assert len(calls) == 1
    assert waited == []
    assert time.monotonic() - started < 0.05
    assert (source / "result.json").exists() and _is_empty(reserved)


def _is_empty(folder: Path) -> bool:
    return not any(folder.iterdir())


def test_an_absent_file_is_removed_without_error(tmp_path: Path) -> None:
    unlink_when_free(tmp_path / "missing.lock")


def test_replacing_an_absent_file_raises_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waited: list[float] = []
    monkeypatch.setattr(filesystem.time, "sleep", waited.append)
    with pytest.raises(FileNotFoundError):
        replace_when_free(tmp_path / "missing.lock", tmp_path / "aside")
    assert waited == []


# --- Real Windows cases, played by the weekly job on windows-latest.


@pytest.mark.skipif(os.name != "nt", reason="the real Windows kernel only")
def test_windows_renames_onto_an_empty_reserved_folder(tmp_path: Path) -> None:
    source, reserved = _trial(tmp_path)
    with pytest.raises(OSError):
        os.replace(source, reserved)
    rename_onto_empty_dir(source, reserved)
    assert (reserved / "result.json").read_text(encoding="utf-8") == "{}"
    assert not source.exists()


@pytest.mark.skipif(os.name != "nt", reason="the real Windows kernel only")
def test_windows_links_on_ntfs(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"lock")
    target = tmp_path / "target.bin"
    assert link_or_copy(source, target) is True
    assert os.path.samefile(source, target)


@pytest.mark.skipif(os.name != "nt", reason="the real Windows kernel only")
def test_windows_prefixes_a_unc_path(tmp_path: Path) -> None:
    drive, tail = os.path.splitdrive(str(tmp_path))
    unc = f"\\\\localhost\\{drive[0]}$" + tail + "\\deep"
    value = native_io_path(unc)
    assert value.startswith("\\\\?\\UNC\\")
    assert value.lower().endswith("\\deep")
