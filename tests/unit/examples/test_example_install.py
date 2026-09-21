"""Fetch, verify and install, exercised against a local tree instead of GitHub."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import CacheCorruptionError, DataRequestError
from hydromodpy.examples import blobs
from hydromodpy.examples.install import install_example
from hydromodpy.examples.manifest import ExampleEntry, ExampleFile

_DEM = b"a regional DEM, shared by several examples\n"
_STEP = b'[simulation]\nname = "tiny"\n'


def _entry(files: tuple[ExampleFile, ...], data: tuple[ExampleFile, ...]) -> ExampleEntry:
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
            ExampleFile(
                repo_path="examples/projects/tiny/step1.toml",
                dest="projects/tiny/step1.toml",
                size=len(_STEP),
                sha256=hashlib.sha256(_STEP).hexdigest(),
            ),
        ),
        data=(
            ExampleFile(
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


def test_install_writes_authored_and_data_files(source_tree, catalog_entry, workspace) -> None:
    report = install_example(catalog_entry, workspace=workspace, source=str(source_tree))

    assert (workspace / "projects" / "tiny" / "step1.toml").read_bytes() == _STEP
    assert (workspace / "data" / "dem" / "dem.tif").read_bytes() == _DEM
    assert sorted(report.written) == ["data/dem/dem.tif", "projects/tiny/step1.toml"]
    assert report.everything_was_cached is False
    assert report.downloaded_bytes == len(_STEP) + len(_DEM)
    assert report.entry_config == "step1.toml"


def test_second_install_downloads_nothing(source_tree, catalog_entry, workspace) -> None:
    install_example(catalog_entry, workspace=workspace, source=str(source_tree))
    again = install_example(catalog_entry, workspace=workspace, source=str(source_tree))

    assert again.everything_was_cached is True
    assert again.written == []
    assert sorted(again.unchanged) == ["data/dem/dem.tif", "projects/tiny/step1.toml"]


def test_the_blob_survives_the_workspace(source_tree, catalog_entry, workspace, tmp_path) -> None:
    """The file is the cached unit: a second workspace re-downloads nothing."""
    install_example(catalog_entry, workspace=workspace, source=str(source_tree))
    other = tmp_path / "ws2"
    (other / "data").mkdir(parents=True)
    report = install_example(catalog_entry, workspace=other, source=str(source_tree))
    assert report.everything_was_cached is True
    assert sorted(report.written) == ["data/dem/dem.tif", "projects/tiny/step1.toml"]


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
            ExampleFile(
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


def test_blobs_are_sharded_by_the_first_two_hex_digits() -> None:
    sha = hashlib.sha256(_DEM).hexdigest()
    path = blobs.blob_path(sha)
    assert path.name == sha
    assert path.parent.name == sha[:2]
