"""Names of result directories: hash, rename, import of a published run.

Reservation of versions is covered by ``test_reserve_version_dirname.py`` and
``test_a_name_is_never_reassigned.py``.
"""

from __future__ import annotations

import json
import os
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ImportConflictError
from hydromodpy.results.catalog.registration import (
    NameTakenError,
    check_name_free,
    import_publication,
    rename_case,
    run_dir_holding,
    run_identity_hash,
    split_stem_version,
)
from hydromodpy.results.ledger import sha256_of
from hydromodpy.results.manifest import RUN_RECORD_MANIFEST_VERSION
from hydromodpy.results.outcome import Outcome, write_outcome
from hydromodpy.results.publication import (
    Publication,
    PublicationSource,
    write_publication,
)
from hydromodpy.results.storage.contract import PUBLICATION_FILENAME, RUN_MANIFEST_FILENAME
from hydromodpy.results.trash import DirectoryInUseError, gc_trash, read_tombstones, trash_run

AT = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
SIM_ID = "9a4f0c1e-0000-4000-8000-000000000001"


def _make_run(project: Path, name: str, *, sim_id: str | None = None) -> Path:
    run_dir = project / "runs" / name
    (run_dir / "tables.parquet").mkdir(parents=True)
    (run_dir / "tables.parquet" / "simulation.parquet").write_bytes(b"PAR1-demo")
    (run_dir / "config.toml").write_text("[flow]\nk = 1e-5\n", encoding="utf-8")
    if sim_id is not None:
        manifest = {
            "manifest_version": RUN_RECORD_MANIFEST_VERSION,
            "run": {"sim_id": sim_id, "name": name},
        }
        (run_dir / RUN_MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
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


def test_the_identity_hash_leaves_the_workspace_out() -> None:
    base = {"flow": {"k": 1e-5}, "workspace": {"project_root": "/a", "root": "/ws"}}
    moved = {"flow": {"k": 1e-5}, "workspace": {"project_root": "/b", "catalog_path": "/x"}}
    other = {"flow": {"k": 2e-5}, "workspace": {"project_root": "/a"}}
    assert run_identity_hash(base) == run_identity_hash(moved)
    assert run_identity_hash(base) != run_identity_hash(other)


def test_the_name_is_not_part_of_the_identity() -> None:
    assert run_identity_hash({"simulation": {"name": "a"}, "flow": {"k": 1}}) == run_identity_hash(
        {"simulation": {"name": "b"}, "flow": {"k": 1}}
    )


def test_the_version_suffix_is_read_once() -> None:
    assert split_stem_version("J0014010-base.v12") == ("J0014010-base", 12)
    assert split_stem_version("calibration") == ("calibration", None)
    assert split_stem_version("k2e_5.vx") == ("k2e_5.vx", None)


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
    with pytest.raises(ValueError, match="not a directory name"):
        rename_case(project, "runs/a", "two words")


def test_a_published_directory_is_imported_under_the_next_version(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    source = _make_run(lab, "nancon_monthly.v2", sim_id=SIM_ID)
    copy = _publish(source, tmp_path / "copy", rel_dir="runs/nancon_monthly.v2", sim_id=SIM_ID)
    project = tmp_path / "home"
    _make_run(project, "nancon_monthly")

    rel_dir = import_publication(project, copy)

    assert rel_dir == "runs/nancon_monthly.v2"
    imported = project / rel_dir
    assert (imported / RUN_MANIFEST_FILENAME).is_file()
    assert not (imported / PUBLICATION_FILENAME).exists()
    assert not list((project / ".hmp").iterdir())


def test_a_published_tar_is_imported_under_the_name_asked(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    source = _make_run(lab, "nancon_monthly", sim_id=SIM_ID)
    copy = _publish(source, tmp_path / "copy", rel_dir="runs/nancon_monthly", sim_id=SIM_ID)
    archive = tmp_path / "nancon_monthly.tar"
    with tarfile.open(archive, "w") as handle:
        handle.add(copy, arcname="nancon_monthly")
    project = tmp_path / "home"
    assert import_publication(project, archive, name="lab_copy") == "runs/lab_copy"


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


def test_fail_accepts_a_name_nothing_holds(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _make_run(project, "other")
    check_name_free(project, "fresh")
    check_name_free(tmp_path / "empty", "fresh")


def test_fail_refuses_a_name_a_live_run_or_session_holds(tmp_path: Path) -> None:
    """``if_exists = 'fail'`` forbids a substitute name: any version held refuses the stem."""
    project = tmp_path / "p"
    _make_run(project, "shared.v2")
    with pytest.raises(NameTakenError, match=r"runs/shared\.v2"):
        check_name_free(project, "shared")
    (project / "sessions" / "calib").mkdir(parents=True)
    with pytest.raises(NameTakenError, match="sessions/calib"):
        check_name_free(project, "calib")


def test_fail_refuses_a_name_a_trashed_run_still_occupies(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _make_run(project, "gone")
    trash_run(project, "runs/gone", now=AT)
    assert not (project / "runs" / "gone").exists()
    with pytest.raises(NameTakenError, match="trash:runs/gone"):
        check_name_free(project, "gone")


def test_fail_refuses_a_name_a_tombstone_remembers(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _make_run(project, "purged")
    trash_run(project, "runs/purged", now=AT)
    gc_trash(project, older_than=timedelta(0), now=AT + timedelta(days=1))
    assert [stone.rel_dir for stone in read_tombstones(project)] == ["runs/purged"]
    with pytest.raises(NameTakenError, match="tombstone:runs/purged"):
        check_name_free(project, "purged")


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

    monkeypatch.setattr(os, "rename", _crash)
    with pytest.raises(OSError, match="disk unplugged"):
        import_publication(project, copy)
    monkeypatch.undo()
    assert list((project / "runs").iterdir()) == []
    assert list((project / ".hmp").iterdir()) == []
    assert import_publication(project, copy) == "runs/x"
