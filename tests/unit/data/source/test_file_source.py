"""Unit tests for the generic file data source."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import BoundsError
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.data.loading._dispatch import VARIABLE_SPECS
from hydromodpy.data.source.file import DemFile, FileSource
from hydromodpy.data.source.port import FetchRequest
from hydromodpy.data.source.registry import data_sources


def test_file_source_single_file_returns_file_record(tmp_path: Path) -> None:
    data_file = tmp_path / "dem.tif"
    content = b"dem elevation raster bytes"
    data_file.write_bytes(content)
    expected_sha = hashlib.sha256(content).hexdigest()

    source = DemFile(path=data_file)
    out_dir = tmp_path / "out"
    req = FetchRequest(out_dir=out_dir)

    result = source.fetch(req)
    assert result.source_id == "file"
    assert result.kind == "files"
    assert len(result.files) == 1

    rec = result.files[0]
    assert rec.path == data_file
    assert rec.sha256 == expected_sha
    assert rec.origin == "file"
    assert rec.state is None
    # No file written to out_dir
    assert not out_dir.exists()


def test_file_source_directory_returns_sorted_file_records(tmp_path: Path) -> None:
    folder = tmp_path / "chronicles"
    folder.mkdir()
    (folder / "station_b.csv").write_bytes(b"b")
    (folder / "station_a.csv").write_bytes(b"a")
    (folder / ".hidden.csv").write_bytes(b"ignore")

    source = FileSource(path=folder)
    source.section = "hydrometry"
    out_dir = tmp_path / "out"
    req = FetchRequest(out_dir=out_dir)

    result = source.fetch(req)
    assert len(result.files) == 2
    assert result.files[0].path.name == "station_a.csv"
    assert result.files[1].path.name == "station_b.csv"


def test_file_source_refuses_path_outside_allowed_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    outside = tmp_path / "secret" / "dem.tif"
    outside.parent.mkdir()
    outside.write_bytes(b"secret")

    source = DemFile(path=outside)
    bounds = Bounds(allowed_roots=(allowed,))
    req = FetchRequest(out_dir=tmp_path / "out", bounds=bounds)

    with pytest.raises(BoundsError, match="outside the roots"):
        source.fetch(req)


def test_file_source_refuses_absent_path(tmp_path: Path) -> None:
    absent = tmp_path / "nonexistent.tif"
    source = DemFile(path=absent)
    req = FetchRequest(out_dir=tmp_path / "out")

    with pytest.raises(FileNotFoundError, match=r"\[data\.dem\] file source path not found"):
        source.fetch(req)


def test_every_section_has_registered_file_subclass() -> None:
    for var in VARIABLE_SPECS:
        cls = data_sources.get(var, "file")
        assert issubclass(cls, FileSource)
        assert cls.section == var
        assert cls.source_id == "file"
