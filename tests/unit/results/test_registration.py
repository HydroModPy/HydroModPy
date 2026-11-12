"""Names of result directories: hash, rename, import of a published run.

Reservation of versions is covered by ``test_reserve_version_dirname.py`` and
``test_a_name_is_never_reassigned.py``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ConfigError, ImportConflictError
from hydromodpy.core.io import filesystem
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.results.catalog.registration import (
    NameTakenError,
    import_publication,
    rename_case,
    reserve_version_dirname,
    run_dir_holding,
)
from hydromodpy.results.outcome import Outcome, write_outcome
from hydromodpy.results.publication import (
    Publication,
    PublicationSource,
    write_publication,
)
from hydromodpy.results.record.request_identity import request_id
from hydromodpy.results.storage.contract import RUN_MANIFEST_FILENAME
from hydromodpy.results.trash import DirectoryInUseError, gc_trash, trash_run
from tests._helpers.sealed_runs import manifest_document
from tests._helpers.windows_os import PatchedOs, WindowsOs

AT = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
SIM_ID = "9a4f0c1e-0000-4000-8000-000000000001"


def _make_run(project: Path, name: str, *, sim_id: str | None = None) -> Path:
    run_dir = project / "runs" / name
    (run_dir / "tables.parquet").mkdir(parents=True)
    (run_dir / "tables.parquet" / "simulation.parquet").write_bytes(b"PAR1-demo")
    (run_dir / "config.toml").write_text("[flow]\nk = 1e-5\n", encoding="utf-8")
    if sim_id is not None:
        (run_dir / RUN_MANIFEST_FILENAME).write_text(
            json.dumps(manifest_document(sim_id=sim_id, name=name)), encoding="utf-8"
        )
    return run_dir


def _running(run_dir: Path) -> None:
    write_outcome(
        run_dir,
        Outcome(
            case_id=run_dir.name,
            attempt=1,
            attempt_id="a1",
            status="running",
            written_by="worker",
            started_at=datetime.now(UTC),
            host="here",
            pid=os.getpid(),
        ),
    )


def _publish(source: Path, destination: Path, *, rel_dir: str, sim_id: str) -> Path:
    """Write what ``hmp publish --format dir`` writes: the run files and PUBLICATION.json."""
    import shutil

    shutil.copytree(source, destination)
    (destination / "ro-crate-metadata.json").write_text("{}", encoding="utf-8")
    files = {
        path.relative_to(destination).as_posix(): sha256_of(path)
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }
    write_publication(
        destination,
        Publication(
            source=PublicationSource(project="lab", rel_dir=rel_dir, sim_id=sim_id),
            files=files,
            hydromodpy_version="2.0.0a5",
            published_at=AT,
            format="dir",
        ),
    )
    return destination


def _request_id(document: dict) -> str:
    return request_id(document, {}, edition="2.0")


def test_the_name_is_not_part_of_the_request_id() -> None:
    assert _request_id({"simulation": {"name": "a"}, "flow": {"k": 1}}) == _request_id(
        {"simulation": {"name": "b"}, "flow": {"k": 1}}
    )


def test_a_rename_moves_the_run_and_its_session_together(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _make_run(project, "calibration", sim_id=SIM_ID)
    (project / "sessions" / "calibration").mkdir(parents=True)
    assert rename_case(project, "runs/calibration", "calage_nm") == (
        "runs/calage_nm",
        "sessions/calage_nm",
    )
    assert (project / "runs" / "calage_nm" / RUN_MANIFEST_FILENAME).is_file()
    assert (project / "sessions" / "calage_nm").is_dir()
    assert not (project / "runs" / "calibration").exists()
    assert not (project / "sessions" / "calibration").exists()
    assert run_dir_holding(project, SIM_ID) == "runs/calage_nm"


def test_a_rename_onto_a_live_name_is_refused(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _make_run(project, "a")
    _make_run(project, "b")
    with pytest.raises(NameTakenError):
        rename_case(project, "runs/a", "b")
    (project / "sessions" / "c").mkdir(parents=True)
    with pytest.raises(NameTakenError):
        rename_case(project, "runs/a", "c")
    assert (project / "runs" / "a").is_dir()


def test_a_rename_never_takes_a_deleted_name(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _make_run(project, "old")
    _make_run(project, "kept")
    trash_run(project, "runs/old", now=AT)
    with pytest.raises(NameTakenError, match="never given out again"):
        rename_case(project, "runs/kept", "old")
    gc_trash(project, older_than=timedelta(0), now=AT + timedelta(days=1))
    with pytest.raises(NameTakenError):
        rename_case(project, "runs/kept", "old")
    assert rename_case(project, "runs/kept", "old.v2") == ("runs/old.v2",)


def test_a_running_directory_is_never_renamed(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _running(_make_run(project, "busy"))
    with pytest.raises(DirectoryInUseError, match="running"):
        rename_case(project, "runs/busy", "idle")
    assert (project / "runs" / "busy").is_dir()


def test_a_rename_refuses_a_trial_and_a_name_that_is_no_directory(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _make_run(project, "a")
    with pytest.raises(ValueError, match="kept trial"):
        rename_case(project, "sessions/cal/trials/0004", "x")
    with pytest.raises(ConfigError, match="Write 'two_words'"):
        rename_case(project, "runs/a", "two words")
    with pytest.raises(ConfigError, match="device name"):
        rename_case(project, "runs/a", "con")


def test_a_copy_whose_digest_differs_never_enters_the_runs(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    source = _make_run(lab, "x", sim_id=SIM_ID)
    copy = _publish(source, tmp_path / "copy", rel_dir="runs/x", sim_id=SIM_ID)
    (copy / "config.toml").write_text("[flow]\nk = 9\n", encoding="utf-8")
    project = tmp_path / "home"
    with pytest.raises(ValueError, match="config.toml does not match"):
        import_publication(project, copy)
    assert not (project / "runs" / "x").exists()


def test_a_run_already_in_the_project_is_a_write_conflict(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    source = _make_run(lab, "x", sim_id=SIM_ID)
    copy = _publish(source, tmp_path / "copy", rel_dir="runs/x", sim_id=SIM_ID)
    project = tmp_path / "home"
    import_publication(project, copy)
    with pytest.raises(ImportConflictError, match="runs/x"):
        import_publication(project, copy)
    assert sorted(path.name for path in (project / "runs").iterdir()) == ["x"]


def test_a_directory_without_publication_is_refused(tmp_path: Path) -> None:
    source = _make_run(tmp_path / "lab", "x", sim_id=SIM_ID)
    with pytest.raises(ValueError, match="PUBLICATION.json"):
        import_publication(tmp_path / "home", source)


def test_a_file_the_publication_does_not_list_is_refused(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    source = _make_run(lab, "x", sim_id=SIM_ID)
    copy = _publish(source, tmp_path / "copy", rel_dir="runs/x", sim_id=SIM_ID)
    (copy / "tables.parquet" / "planted.parquet").write_bytes(b"PAR1-planted")
    project = tmp_path / "home"
    with pytest.raises(ValueError, match="planted.parquet not listed"):
        import_publication(project, copy)
    assert not (project / "runs").exists() or not list((project / "runs").iterdir())


def test_an_interrupted_import_leaves_no_partial_directory(tmp_path: Path, monkeypatch) -> None:
    lab = tmp_path / "lab"
    source = _make_run(lab, "x", sim_id=SIM_ID)
    copy = _publish(source, tmp_path / "copy", rel_dir="runs/x", sim_id=SIM_ID)
    project = tmp_path / "home"

    def _crash(*_args, **_kwargs):
        raise OSError("disk unplugged")

    monkeypatch.setattr(os, "replace", _crash)
    monkeypatch.setattr(os, "rename", _crash)
    with pytest.raises(OSError, match="disk unplugged"):
        import_publication(project, copy)
    monkeypatch.undo()
    assert list((project / "runs").iterdir()) == []
    assert list((project / ".hmp").iterdir()) == []
    assert import_publication(project, copy) == "runs/x"


LONG_ROOT_SENTENCE = (
    "The project folder {root} is {length} characters long. On Windows a project writes paths "
    "up to 160 characters below its folder, and MODFLOW 6 and DuckDB open no path longer than "
    "259, so the folder may hold 99 characters at most. Move the project to a shorter folder, "
    "for example D:\\hmp\\<organisation>\\projects\\<name>."
)


def _long_root(tmp_path: Path, length: int) -> Path:
    """A folder of at least ``length`` characters (the scratch root is already long)."""
    root = tmp_path / "p"
    return Path(str(root) + "x" * max(length - len(str(root)), 0))


def test_a_reservation_in_a_folder_too_long_for_windows_is_refused_and_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _long_root(tmp_path, 120)
    monkeypatch.setattr(filesystem, "os", WindowsOs())

    with pytest.raises(ConfigError) as caught:
        reserve_version_dirname(root, "run", "case")

    assert str(caught.value) == LONG_ROOT_SENTENCE.format(root=root, length=len(str(root)))
    assert not root.exists()


def _published_copy(tmp_path: Path) -> tuple[Path, Path]:
    source = _make_run(tmp_path / "lab", "x", sim_id=SIM_ID)
    copy = _publish(source, tmp_path / "copy", rel_dir="runs/x", sim_id=SIM_ID)
    return copy, tmp_path / "home"


def test_a_neighbour_that_takes_the_reserved_name_keeps_its_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy, project = _published_copy(tmp_path)
    real_rmdir = os.rmdir

    def refuse(source: object, target: object) -> None:
        raise PermissionError(5, "Access is denied")

    def rmdir_then_neighbour_creates(path: object) -> None:
        real_rmdir(path)
        os.mkdir(path)
        (Path(str(path)) / "theirs.txt").write_text("theirs", encoding="utf-8")

    monkeypatch.setattr(
        filesystem, "os", PatchedOs(name="nt", replace=refuse, rmdir=rmdir_then_neighbour_creates)
    )
    monkeypatch.setattr(filesystem, "WINDOWS_PATH_LIMIT", 10**6)  # tmp_path is long

    with pytest.raises(FileExistsError):
        import_publication(project, copy)

    assert (project / "runs" / "x" / "theirs.txt").read_text(encoding="utf-8") == "theirs"
