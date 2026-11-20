"""The archive of a data cache: written with each sidecar, restored only when every file checks."""

from __future__ import annotations

import re
import sys
import tarfile
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import CacheCorruptionError, SchemaVersionMismatchError
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.data.provenance import archive as archive_module
from hydromodpy.data.provenance.archive import archive_data, restore_archive
from hydromodpy.data.provenance.lockfile import LOCKFILE_NAME
from hydromodpy.data.provenance.sidecars import (
    CacheIndex,
    empty_path_for,
    load_sidecar,
    scan,
    sidecar_path_for,
)


def _seed(tmp: Path) -> tuple[Path, list[Path]]:
    data_root = tmp / "workspace" / "data"
    index = CacheIndex(data_root)
    files = []
    for variable, name, body in (
        ("hydrometry", "hydrometry_hubeau_A.csv", "datetime,value\n2020-01-01,1.0\n"),
        ("recharge", "recharge_sim2_x.nc", "netcdf bytes"),
    ):
        path = data_root / variable / name
        path.parent.mkdir(parents=True)
        path.write_text(body)
        index.record(path, variable=variable, source=name.split("_")[1], bbox=(0, 0, 1, 1))
        files.append(path)
    return data_root, files


@pytest.mark.parametrize("suffix", [".tar", ".tar.gz"])
def test_an_archive_restores_rows_of_the_cache(tmp_path: Path, suffix: str) -> None:
    data_root, files = _seed(tmp_path)
    archive = tmp_path / f"export{suffix}"
    archive_data(data_root, archive, lockfile_dest=tmp_path / LOCKFILE_NAME)

    target = tmp_path / "elsewhere" / "data"
    restored = restore_archive(archive, target)

    assert sorted(p.relative_to(target) for p in restored) == sorted(
        p.relative_to(data_root) for p in files
    )
    rows = {row.path.relative_to(target): row for row in scan(target).rows}
    for src in files:
        row = rows[src.relative_to(data_root)]
        assert row.sha256 == sha256_of(src)
        assert load_sidecar(row.path) == load_sidecar(src)


def test_a_zstandard_archive_round_trips(tmp_path: Path) -> None:
    pytest.importorskip("zstandard")
    data_root, files = _seed(tmp_path)
    archive = tmp_path / "export.tar.zst"
    archive_data(data_root, archive, lockfile_dest=tmp_path / LOCKFILE_NAME)
    target = tmp_path / "restored"
    restore_archive(archive, target)
    for src in files:
        assert sha256_of(target / src.relative_to(data_root)) == sha256_of(src)


def test_an_empty_answer_travels_as_its_sidecar_alone(tmp_path: Path) -> None:
    data_root, _files = _seed(tmp_path)
    empty = CacheIndex(data_root).record_empty(
        empty_path_for(data_root / "hydrometry", "hydrometry_hubeau_Z"),
        variable="hydrometry",
        source="hubeau",
        station_id="Z",
    )
    archive = tmp_path / "export.tar"
    archive_data(data_root, archive, lockfile_dest=tmp_path / LOCKFILE_NAME)
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
    assert "artefacts/empty/hydrometry/hydrometry_hubeau_Z_empty.csv.json" in names
    assert "artefacts/empty/hydrometry/hydrometry_hubeau_Z_empty.csv" not in names

    target = tmp_path / "elsewhere" / "data"
    restore_archive(archive, target)

    restored = target / empty.sidecar_path.relative_to(data_root)
    assert load_sidecar(restored.with_suffix("")) == load_sidecar(empty.path)
    assert [row.station_id for row in scan(target).rows if row.empty] == ["Z"]


def _tamper(path: Path) -> None:
    path.write_text("other bytes\n")


def _drop_sidecar(path: Path) -> None:
    sidecar_path_for(path).unlink()


@pytest.mark.parametrize(
    ("damage", "said"),
    [
        pytest.param(_tamper, "expected sha256", id="tampered"),
        pytest.param(Path.unlink, "absent from the archive", id="missing"),
        pytest.param(_drop_sidecar, "its sidecar is absent", id="without sidecar"),
    ],
)
def test_a_bad_archive_is_refused_and_leaves_nothing(tmp_path: Path, damage, said: str) -> None:
    data_root, (src, _) = _seed(tmp_path)
    archive = tmp_path / "good.tar"
    archive_data(data_root, archive, lockfile_dest=tmp_path / LOCKFILE_NAME)
    unpacked = tmp_path / "unpacked"
    with tarfile.open(archive) as tar:
        tar.extractall(unpacked, filter="data")
    damage(unpacked / "artefacts" / sha256_of(src) / src.name)
    bad = tmp_path / "bad.tar"
    with tarfile.open(bad, "w") as tar:
        tar.add(unpacked, arcname=".")

    target = tmp_path / "out" / "data"
    with pytest.raises(CacheCorruptionError, match=re.escape(said)):
        restore_archive(bad, target)
    assert [p for p in target.parent.iterdir() if p != target] == []
    assert list(target.iterdir()) == []


@pytest.mark.parametrize(
    "escape",
    [
        pytest.param("../../project.toml", id="climbs out"),
        pytest.param("/{outside}/project.toml", id="absolute"),
    ],
)
def test_a_record_whose_path_leaves_the_data_folder_is_refused(tmp_path: Path, escape: str) -> None:
    """The lockfile of an archive comes from elsewhere: a path out of data/ writes nothing."""
    data_root, (src, _) = _seed(tmp_path)
    archive = tmp_path / "good.tar"
    archive_data(data_root, archive, lockfile_dest=tmp_path / LOCKFILE_NAME)
    unpacked = tmp_path / "unpacked"
    with tarfile.open(archive) as tar:
        tar.extractall(unpacked, filter="data")
    outside = tmp_path / "out"
    lockfile = unpacked / LOCKFILE_NAME
    named = src.relative_to(data_root).as_posix()
    escape = escape.format(outside=outside.as_posix().lstrip("/"))
    lockfile.write_text(lockfile.read_text().replace(f'"{named}"', f'"{escape}"'))
    bad = tmp_path / "bad.tar"
    with tarfile.open(bad, "w") as tar:
        tar.add(unpacked, arcname=".")

    target = outside / "workspace" / "data"
    with pytest.raises(CacheCorruptionError, match=re.escape("leaves the data folder")):
        restore_archive(bad, target)
    assert not (outside / "project.toml").exists()
    assert list(target.iterdir()) == []


def test_an_archive_without_its_lockfile_is_refused(tmp_path: Path) -> None:
    bare = tmp_path / "bare.tar"
    with tarfile.open(bare, "w"):
        pass
    with pytest.raises(CacheCorruptionError, match=f"holds no {LOCKFILE_NAME}"):
        restore_archive(bare, tmp_path / "restored")


def test_an_archive_of_a_pre_release_is_refused_by_its_lockfile(tmp_path: Path) -> None:
    old = tmp_path / "old"
    old.mkdir()
    (old / LOCKFILE_NAME).write_text('schema = "hydromodpy.lock.v1"\n')
    archive = tmp_path / "old.tar"
    with tarfile.open(archive, "w") as tar:
        tar.add(old / LOCKFILE_NAME, arcname=LOCKFILE_NAME)
    with pytest.raises(SchemaVersionMismatchError, match="hmp data lock"):
        restore_archive(archive, tmp_path / "restored")


@pytest.mark.parametrize("opener", ["_open_writer", "_open_reader"])
def test_a_zst_archive_without_zstandard_says_so(
    opener: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "zstandard", None)
    with pytest.raises(RuntimeError, match="zstandard is required"):
        getattr(archive_module, opener)(tmp_path / "frozen.tar.zst")
