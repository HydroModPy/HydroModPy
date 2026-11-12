"""Fetch, verify and install, exercised against a local tree instead of GitHub."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import CacheCorruptionError, DataRequestError
from hydromodpy.core.payload.index import PayloadFile, PayloadStation
from hydromodpy.project.examples import blobs
from hydromodpy.project.examples.install import install_example
from hydromodpy.project.examples.manifest import ExampleEntry

_DEM = b"a regional DEM, shared by several examples\n"
_STEP = b'[simulation]\nname = "tiny"\n'


def _entry(files: tuple[PayloadFile, ...], data: tuple[PayloadFile, ...]) -> ExampleEntry:
    return ExampleEntry(
        id="t1",
        directory="tiny",
        title="Tiny",
        summary="A two-file example.",
        runtime="instant",
        entry_config="step1.toml",
        files=files,
        data=data,
    )


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    """A checkout-shaped tree the installer can be pointed at with no network."""
    root = tmp_path / "checkout"
    (root / "examples" / "projects" / "tiny").mkdir(parents=True)
    (root / "examples" / "data" / "dem").mkdir(parents=True)
    (root / "examples" / "projects" / "tiny" / "step1.toml").write_bytes(_STEP)
    (root / "examples" / "data" / "dem" / "dem.tif").write_bytes(_DEM)
    return root


@pytest.fixture
def catalog_entry() -> ExampleEntry:
    return _entry(
        files=(
            PayloadFile(
                repo_path="examples/projects/tiny/step1.toml",
                dest="projects/tiny/step1.toml",
                size=len(_STEP),
                sha256=hashlib.sha256(_STEP).hexdigest(),
            ),
        ),
        data=(
            PayloadFile(
                repo_path="examples/data/dem/dem.tif",
                dest="data/dem/dem.tif",
                size=len(_DEM),
                sha256=hashlib.sha256(_DEM).hexdigest(),
            ),
        ),
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True)
    (root / "projects").mkdir(parents=True)
    return root


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every blob written by a test out of the developer's real cache."""
    monkeypatch.setenv("HMP_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv(blobs.SOURCE_ENV, raising=False)


def test_second_install_downloads_nothing(source_tree, catalog_entry, workspace) -> None:
    install_example(catalog_entry, workspace=workspace, source=str(source_tree))
    again = install_example(catalog_entry, workspace=workspace, source=str(source_tree))

    assert again.everything_was_cached is True
    assert again.written == []
    assert sorted(again.unchanged) == ["data/dem/dem.tif", "projects/tiny/step1.toml"]


def test_a_checksum_mismatch_writes_nothing(source_tree, catalog_entry, workspace) -> None:
    (source_tree / "examples" / "data" / "dem" / "dem.tif").write_bytes(b"another DEM entirely\n")

    with pytest.raises(CacheCorruptionError, match="dem.tif"):
        install_example(catalog_entry, workspace=workspace, source=str(source_tree))

    assert not (workspace / "data" / "dem" / "dem.tif").exists()
    assert list(blobs.blobs_dir().rglob("*.part")) == []


def test_a_corrupted_cached_blob_is_refused_and_evicted(
    source_tree, catalog_entry, workspace, tmp_path
) -> None:
    """A cache hit is verified too: the blob's name is its hash, so a drift is corruption."""
    install_example(catalog_entry, workspace=workspace, source=str(source_tree))
    dem = catalog_entry.data[0]
    blobs.blob_path(dem.sha256).write_bytes(b"silently wrong bytes\n")

    other = tmp_path / "ws2"
    (other / "data").mkdir(parents=True)
    with pytest.raises(CacheCorruptionError, match="dem.tif"):
        install_example(catalog_entry, workspace=other, source=str(source_tree))

    assert not (other / "data" / "dem" / "dem.tif").exists()
    assert not blobs.blob_path(dem.sha256).exists()

    repaired = install_example(catalog_entry, workspace=other, source=str(source_tree))
    assert (other / "data" / "dem" / "dem.tif").read_bytes() == _DEM
    assert "data/dem/dem.tif" in repaired.written


def test_an_edited_destination_is_kept_unless_forced(source_tree, catalog_entry, workspace) -> None:
    install_example(catalog_entry, workspace=workspace, source=str(source_tree))
    edited = workspace / "projects" / "tiny" / "step1.toml"
    edited.write_bytes(b"# my own notes\n")

    kept = install_example(catalog_entry, workspace=workspace, source=str(source_tree))
    assert kept.kept == ["projects/tiny/step1.toml"]
    assert edited.read_bytes() == b"# my own notes\n"

    forced = install_example(
        catalog_entry, workspace=workspace, source=str(source_tree), force=True
    )
    assert forced.written == ["projects/tiny/step1.toml"]
    assert edited.read_bytes() == _STEP


def test_a_destination_escaping_the_workspace_is_refused(source_tree, workspace) -> None:
    entry = _entry(
        files=(
            PayloadFile(
                repo_path="examples/projects/tiny/step1.toml",
                dest="../escaped.toml",
                size=len(_STEP),
                sha256=hashlib.sha256(_STEP).hexdigest(),
            ),
        ),
        data=(),
    )
    with pytest.raises(DataRequestError, match="outside the workspace"):
        install_example(entry, workspace=workspace, source=str(source_tree))


def test_a_directory_without_data_is_not_a_workspace(source_tree, catalog_entry, tmp_path) -> None:
    with pytest.raises(DataRequestError, match="hmp workspace init"):
        install_example(catalog_entry, workspace=tmp_path / "nowhere", source=str(source_tree))


def test_the_source_env_replaces_the_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    assert blobs.resolve_source("main").endswith("/main")
    monkeypatch.setenv(blobs.SOURCE_ENV, "file:///somewhere/")
    assert blobs.resolve_source("main") == "file:///somewhere"


_REGISTRY = "data/hydrometry/hydrometry_custom_LOC.csv"
_NANCON = (
    ("id", "NANCON"),
    ("x", "389285.910"),
    ("y", "6816518.749"),
    ("crs", "EPSG:2154"),
    ("unit", "m3/s"),
    ("constant", "false"),
)


def _with_station(entry: ExampleEntry) -> ExampleEntry:
    return replace(entry, stations=(PayloadStation(dest=_REGISTRY, row=_NANCON),))


def test_a_station_row_joins_the_scaffolded_registry(source_tree, catalog_entry, workspace) -> None:
    """`hmp workspace init` writes a registry with a header and no row."""
    registry = workspace / _REGISTRY
    registry.parent.mkdir(parents=True)
    registry.write_text("id,x,y,crs,unit\nMINE,1,2,EPSG:2154,m3/s\n", encoding="utf-8")

    report = install_example(
        _with_station(catalog_entry), workspace=workspace, source=str(source_tree)
    )

    lines = registry.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "id,x,y,crs,unit,constant"
    assert lines[1] == "MINE,1,2,EPSG:2154,m3/s,"
    assert lines[2] == "NANCON,389285.910,6816518.749,EPSG:2154,m3/s,false"
    assert report.stations_written == [f"{_REGISTRY} (station NANCON)"]


def test_an_edited_station_row_is_kept_unless_forced(source_tree, catalog_entry, workspace) -> None:
    registry = workspace / _REGISTRY
    registry.parent.mkdir(parents=True)
    registry.write_text("id,x,y,crs,unit\nNANCON,0,0,EPSG:2154,l/s\n", encoding="utf-8")
    entry = _with_station(catalog_entry)

    kept = install_example(entry, workspace=workspace, source=str(source_tree))
    assert kept.kept == [f"{_REGISTRY} (station NANCON)"]
    assert "NANCON,0,0" in registry.read_text(encoding="utf-8")

    forced = install_example(entry, workspace=workspace, source=str(source_tree), force=True)
    assert forced.stations_written == [f"{_REGISTRY} (station NANCON)"]
    assert "NANCON,389285.910" in registry.read_text(encoding="utf-8")


def test_the_report_gives_its_json_form(source_tree, catalog_entry, workspace) -> None:
    report = install_example(catalog_entry, workspace=workspace, source=str(source_tree))
    document = json.loads(json.dumps(report.to_dict()))
    assert document == {
        "workspace": str(workspace.resolve()),
        "project_dir": str(report.project_dir),
        "entry_config": "step1.toml",
        "source": str(source_tree),
        "downloaded": report.downloaded,
        "downloaded_bytes": len(_STEP) + len(_DEM),
        "written": report.written,
        "unchanged": [],
        "kept": [],
        "stations_written": [],
    }


def test_the_entry_gives_its_json_form(catalog_entry) -> None:
    station = PayloadStation(dest="data/hydrometry/LOC.csv", row=(("id", "X1"), ("name", "Gauge")))
    document = json.loads(json.dumps(replace(catalog_entry, stations=(station,)).to_dict()))
    assert document["id"] == "t1"
    assert document["total_size"] == len(_STEP) + len(_DEM)
    assert [item["dest"] for item in document["files"]] == ["projects/tiny/step1.toml"]
    assert [item["dest"] for item in document["data"]] == ["data/dem/dem.tif"]
    assert document["data"][0]["sha256"] == hashlib.sha256(_DEM).hexdigest()
    assert document["stations"] == [
        {"dest": "data/hydrometry/LOC.csv", "row": {"id": "X1", "name": "Gauge"}}
    ]
