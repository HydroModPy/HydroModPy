"""Every refusal of the data cache, each with the sentence that says what to do."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.core.exceptions import DataCacheError, FrozenDataError, SchemaVersionMismatchError
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.data.provenance.lockfile import (
    LockedInputs,
    project_lockfile_path,
    read_locked_inputs,
    read_lockfile_inputs,
    reject_frozen_download,
    reject_frozen_user_file,
    user_file_input,
    write_lockfile,
)
from hydromodpy.data.provenance.sidecars import (
    FORMER_CACHE_DATABASE,
    CacheIndex,
    Sidecar,
    empty_path_for,
    former_cache_sentence,
    load_sidecar,
    prune,
    scan,
    write_sidecar,
)

CORPUS_ISLAND = (
    Path(__file__).resolve().parents[3]
    / "regression"
    / "frozen_documents"
    / "v2.0.0-pre"
    / "current"
    / "island"
)


@pytest.fixture
def frozen(tmp_path: Path) -> tuple[Path, Path, Path, LockedInputs]:
    """A project whose lockfile pins station A and the user file ``inputs/dem.tif``, and that lockfile read."""
    project = tmp_path / "project"
    data_root = project / "data"
    folder = data_root / "hydrometry"
    folder.mkdir(parents=True)
    chronicle = folder / "hydrometry_hubeau_A_2000.csv"
    chronicle.write_text("datetime,value\n2000-01-01,1.0\n")
    CacheIndex(data_root).record(chronicle, variable="hydrometry", source="hubeau", station_id="A")
    mine = project / "inputs" / "dem.tif"
    mine.parent.mkdir()
    mine.write_bytes(b"dem")
    user = user_file_input(mine, variable="dem", project_root=project, sha256=sha256_of(mine))
    write_lockfile(project_lockfile_path(project), data_root, user_files=[user])
    return project, data_root, chronicle, read_locked_inputs(project)


def _record_other(data_root: Path, locked: LockedInputs | None = None) -> None:
    other = data_root / "hydrometry" / "hydrometry_hubeau_B_2000.csv"
    other.write_text("datetime,value\n")
    CacheIndex(data_root, locked=locked).record(
        other, variable="hydrometry", source="hubeau", station_id="B"
    )


def _other_bytes_under_the_same_name(data_root: Path, locked: LockedInputs) -> None:
    path = data_root / "hydrometry" / "hydrometry_hubeau_A_2000.csv"
    path.write_text("datetime,value\n2000-01-01,2.0\n")
    sidecar = load_sidecar(path).model_copy(update={"sha256": sha256_of(path)})
    write_sidecar(path, sidecar)
    CacheIndex(data_root, locked=locked).find("hydrometry", "hubeau", station_id="A")


def _empty_answer(data_root: Path, locked: LockedInputs) -> None:
    CacheIndex(data_root, locked=locked).record_empty(
        empty_path_for(data_root / "hydrometry", "hydrometry_hubeau_C"),
        variable="hydrometry",
        source="hubeau",
        station_id="C",
    )


def _empty_answer_for_a_pinned_station(data_root: Path, locked: LockedInputs) -> None:
    folder = data_root / "hydrometry"
    write_sidecar(
        empty_path_for(folder, "hydrometry_hubeau_A"),
        Sidecar(source="hubeau", variable="hydrometry", station_id="A", empty=True),
    )
    (folder / "hydrometry_hubeau_A_2000.csv").unlink()
    (folder / "hydrometry_hubeau_A_2000.csv.json").unlink()
    CacheIndex(data_root, locked=locked).find("hydrometry", "hubeau", station_id="A")


def _unpinned_empty_answer(data_root: Path, locked: LockedInputs) -> None:
    write_sidecar(
        empty_path_for(data_root / "hydrometry", "hydrometry_hubeau_E"),
        Sidecar(source="hubeau", variable="hydrometry", station_id="E", empty=True),
    )
    CacheIndex(data_root, locked=locked).find("hydrometry", "hubeau", station_id="E")


def _changed_user_file(data_root: Path, locked: LockedInputs) -> None:
    mine = data_root.parent / "inputs" / "dem.tif"
    mine.write_bytes(b"other dem")
    reject_frozen_user_file(locked, variable="dem", path=mine)


def _unpinned_user_file(data_root: Path, locked: LockedInputs) -> None:
    other = data_root.parent / "inputs" / "other.tif"
    other.write_bytes(b"other")
    reject_frozen_user_file(locked, variable="dem", path=other)


_FROZEN_REFUSALS: dict[str, tuple[Callable[[Path, LockedInputs], object], str]] = {
    "a miss": (
        lambda root, locked: CacheIndex(root, locked=locked).find(
            "hydrometry", "hubeau", station_id="Z"
        ),
        "forbids cache misses: hydrometry/hubeau/Z is absent from the data cache",
    ),
    "a row the lockfile does not pin": (
        lambda root, locked: (
            _record_other(root),
            CacheIndex(root, locked=locked).find("hydrometry", "hubeau", station_id="B"),
        ),
        "forbids data cache rows absent from hydromodpy.lock",
    ),
    "a row of other bytes": (_other_bytes_under_the_same_name, "SHA-256 mismatch"),
    "a new record": (
        lambda root, locked: _record_other(root, locked),
        "forbids registering a downloaded artefact absent",
    ),
    "a new empty answer": (_empty_answer, "forbids registering a downloaded artefact absent"),
    "an empty answer the lockfile does not pin": (
        _unpinned_empty_answer,
        r"absent from hydromodpy.lock: hydrometry/hubeau/E \(an empty answer\)",
    ),
    "an empty answer where a file is pinned": (
        _empty_answer_for_a_pinned_station,
        "pins the file hydrometry/hydrometry_hubeau_A_2000.csv",
    ),
    "a download": (
        lambda root, locked: reject_frozen_download(
            locked, variable="hydrometry", source="hubeau", station_id="A", detail="is asked"
        ),
        "forbids a download: hydrometry/hubeau/A is asked",
    ),
    "a user file of other bytes": (_changed_user_file, "user file whose SHA-256 does not match"),
    "a user file the lockfile does not pin": (
        _unpinned_user_file,
        "user file absent from hydromodpy.lock",
    ),
}


@pytest.mark.parametrize(("act", "said"), _FROZEN_REFUSALS.values(), ids=_FROZEN_REFUSALS.keys())
def test_frozen_mode_refuses(
    frozen: tuple[Path, Path, Path, LockedInputs],
    act: Callable[[Path, LockedInputs], object],
    said: str,
) -> None:
    _, data_root, _, locked = frozen
    with pytest.raises(FrozenDataError, match=said):
        act(data_root, locked)


def test_the_same_acts_pass_without_a_lockfile(
    frozen: tuple[Path, Path, Path, LockedInputs],
) -> None:
    """A run that is not frozen hands ``None``: no refusal reads any state of the process."""
    project, data_root, _, _ = frozen
    assert CacheIndex(data_root).find("hydrometry", "hubeau", station_id="Z") is None
    _record_other(data_root)
    reject_frozen_download(None, variable="hydrometry", source="hubeau", station_id="A", detail="x")
    reject_frozen_user_file(None, variable="dem", path=project / "inputs" / "other.tif")


def test_frozen_mode_serves_what_the_lockfile_pins(
    frozen: tuple[Path, Path, Path, LockedInputs],
) -> None:
    project, data_root, chronicle, locked = frozen
    row = CacheIndex(data_root, locked=locked).find("hydrometry", "hubeau", station_id="A")
    assert row is not None and row.path == chronicle
    reject_frozen_user_file(locked, variable="dem", path=project / "inputs" / "dem.tif")


def _pinned_empty_project(tmp_path: Path) -> tuple[Path, Path]:
    """A project whose lockfile pins station E as an empty answer."""
    project = tmp_path / "project"
    data_root = project / "data"
    CacheIndex(data_root).record_empty(
        empty_path_for(data_root / "hydrometry", "hydrometry_hubeau_E"),
        variable="hydrometry",
        source="hubeau",
        station_id="E",
    )
    write_lockfile(project_lockfile_path(project), data_root)
    return project, data_root


def test_frozen_mode_serves_an_empty_answer_the_lockfile_pins(tmp_path: Path) -> None:
    project, data_root = _pinned_empty_project(tmp_path)
    locked = read_locked_inputs(project)
    row = CacheIndex(data_root, locked=locked).find("hydrometry", "hubeau", station_id="E")
    assert row is not None and row.empty


def test_frozen_mode_refuses_a_file_where_the_lockfile_pins_an_empty_answer(
    tmp_path: Path,
) -> None:
    project, data_root = _pinned_empty_project(tmp_path)
    chronicle = data_root / "hydrometry" / "hydrometry_hubeau_E_2000.csv"
    chronicle.write_text("datetime,value\n2000-01-01,1.0\n")
    locked = read_locked_inputs(project)
    with pytest.raises(FrozenDataError, match="pins an empty answer for it"):
        CacheIndex(data_root, locked=locked).record(
            chronicle, variable="hydrometry", source="hubeau", station_id="E"
        )


# -- writing a sidecar ------------------------------------------------------------

_WRITE_REFUSALS = {
    "without its variable": (
        {"source": "hubeau", "sha256": "0" * 64, "bytes": 1},
        "names no variable",
    ),
    "without its size": (
        {"source": "hubeau", "sha256": "0" * 64, "variable": "hydrometry"},
        "carries no bytes",
    ),
}


@pytest.mark.parametrize(("fields", "said"), _WRITE_REFUSALS.values(), ids=_WRITE_REFUSALS.keys())
def test_a_sidecar_is_refused_at_writing(tmp_path: Path, fields: dict, said: str) -> None:
    target = tmp_path / "x.csv"
    target.write_bytes(b"x")
    with pytest.raises(DataCacheError, match=said):
        write_sidecar(target, Sidecar(**fields))
    assert not (tmp_path / "x.csv.json").exists()


def test_an_unknown_key_is_refused_at_writing_and_kept_at_reading(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Sidecar(source="hubeau", sha256="0" * 64, colour="blue")
    target = tmp_path / "x.csv"
    target.write_bytes(b"x")
    (tmp_path / "x.csv.json").write_text(
        json.dumps({"source": "hubeau", "sha256": "0" * 64, "variable": "v", "colour": "blue"})
    )
    assert (load_sidecar(target).__pydantic_extra__ or {}) == {"colour": "blue"}


# -- the database and the lockfile of a pre-release of 2.0 ------------------------------------------


def test_a_data_folder_with_the_former_database_is_refused(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / FORMER_CACHE_DATABASE).write_bytes(b"duckdb")

    for act in (lambda: scan(data_root), lambda: CacheIndex(data_root).rows()):
        with pytest.raises(DataCacheError) as info:
            act()
        assert str(info.value) == former_cache_sentence(data_root.resolve() / "cache.duckdb")
        assert "hmp workspace clean --data-cache" in str(info.value)
        assert "does not read it" in str(info.value)


def test_the_island_of_the_corpus_is_refused_on_a_copy(tmp_path: Path) -> None:
    island = tmp_path / "island"
    shutil.copytree(CORPUS_ISLAND, island)

    with pytest.raises(DataCacheError, match="data cache database of a pre-release of 2.0"):
        scan(island / "data")
    with pytest.raises(SchemaVersionMismatchError, match="hmp data lock"):
        read_lockfile_inputs(island / "hydromodpy.lock")


def test_a_lockfile_of_a_later_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "hydromodpy.lock"
    path.write_text('schema = "hydromodpy.lock.v3"\n')
    with pytest.raises(SchemaVersionMismatchError, match="hydromodpy.lock.v3"):
        read_lockfile_inputs(path)


# -- prune ------------------------------------------------------------------------------


def _fetched(data_root: Path, name: str, when: datetime) -> Path:
    path = data_root / "geology" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(name.encode())
    CacheIndex(data_root).record(path, variable="geology", source="brgm_1m")
    write_sidecar(path, load_sidecar(path).model_copy(update={"fetched_at": when}))
    return path


def test_prune_keeps_a_cited_file_and_names_it(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    cited = _fetched(data_root, "cited.gpkg", datetime(2020, 1, 1))
    old = _fetched(data_root, "old.gpkg", datetime(2020, 1, 1))
    recent = _fetched(data_root, "recent.gpkg", datetime(2026, 1, 1))
    user = data_root / "geology" / "mine.gpkg"
    user.write_bytes(b"mine")
    (data_root / "geology" / "mine.gpkg.json").write_text(
        json.dumps({"source": "file", "sha256": sha256_of(user)})
    )

    report = prune(
        data_root,
        keep=frozenset({sha256_of(cited)}),
        older_than_days=365,
        delete_files=True,
        now=datetime(2026, 6, 1),
    )

    assert report.kept_cited == (cited,)
    assert report.removed == (old,)
    assert report.user_files == 1
    assert cited.exists() and recent.exists() and user.exists()
    assert not old.exists()


def test_prune_without_delete_files_leaves_the_files(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    old = _fetched(data_root, "old.gpkg", datetime(2020, 1, 1))
    prune(data_root, keep=frozenset(), older_than_days=0)
    assert old.exists()
    assert scan(data_root).rows == ()


def test_a_dry_prune_changes_nothing(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    old = _fetched(data_root, "old.gpkg", datetime(2020, 1, 1))
    gone = _fetched(data_root, "gone.gpkg", datetime(2020, 1, 1))
    gone.unlink()

    report = prune(data_root, keep=frozenset(), older_than_days=0, delete_files=True, dry_run=True)

    assert report.removed == (old,)
    assert report.orphans == (data_root / "geology" / "gone.gpkg.json",)
    assert old.exists() and (data_root / "geology" / "gone.gpkg.json").exists()


def test_prune_removes_orphans_whatever_their_age(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    gone = _fetched(data_root, "gone.gpkg", datetime(2026, 1, 1))
    gone.unlink()
    prune(data_root, keep=frozenset(), older_than_days=10_000)
    assert not (data_root / "geology" / "gone.gpkg.json").exists()


def test_prune_needs_the_digests_it_keeps() -> None:
    with pytest.raises(TypeError):
        prune(Path("data"))  # type: ignore[call-arg]


# -- the commands of a pre-release ----------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "said"),
    [
        (["lock", "update"], "hmp data lock"),
        (["lock", "verify"], "hmp data lock --check"),
        (["data", "add", "x.csv"], "inputs/"),
    ],
    ids=["hmp lock update", "hmp lock verify", "hmp data add"],
)
def test_a_command_of_a_pre_release_is_refused_with_its_new_form(
    argv: list[str], said: str, capsys: pytest.CaptureFixture[str]
) -> None:
    from hydromodpy.cli.main import main

    with pytest.raises(SystemExit) as info:
        main(argv)
    assert info.value.code == 2
    assert said in capsys.readouterr().err
