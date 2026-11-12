"""Every refusal of the data cache, each with the sentence that says what to do."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import DataCacheError, FrozenDataError
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.data.provenance.lockfile import (
    LockedInputs,
    project_lockfile_path,
    read_locked_inputs,
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
