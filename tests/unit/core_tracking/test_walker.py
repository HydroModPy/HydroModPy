"""Walker tests on small synthetic Pydantic models."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from hydromodpy.core.tracking import InputFile, collect_input_files


class _Source(BaseModel):
    path: Annotated[
        Path | None,
        InputFile(role="demo", category="data"),
    ] = Field(default=None)


class _Block(BaseModel):
    dem: Annotated[
        Path | None,
        InputFile(role="dem", category="data"),
    ] = Field(default=None)
    polygon: Annotated[
        Path | None,
        InputFile(role="polygon", category="geometry"),
    ] = Field(default=None)
    sources: list[_Source] = Field(default_factory=list)
    scratch: Annotated[
        Path | None,
        InputFile(role="scratch", category="data", portable=False),
    ] = Field(default=None)


class _Root(BaseModel):
    block: _Block
    aux: str = "ignored"


def test_walker_collects_scalar_path(tmp_path: Path) -> None:
    dem_file = tmp_path / "dem.tif"
    dem_file.write_text("x")

    root = _Root(block=_Block(dem=dem_file))
    entries = collect_input_files(root)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.role == "dem"
    assert entry.category == "data"
    assert entry.canonical_path == dem_file.resolve()
    assert entry.portable is True


def test_walker_skips_none_and_empty(tmp_path: Path) -> None:
    root = _Root(block=_Block(dem=None, polygon=None))
    assert collect_input_files(root) == []


def test_walker_descends_into_list_of_models(tmp_path: Path) -> None:
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("x")
    b.write_text("y")

    root = _Root(
        block=_Block(
            sources=[_Source(path=a), _Source(path=b)],
        )
    )
    entries = collect_input_files(root)

    roles = {e.role for e in entries}
    paths = {e.canonical_path for e in entries}
    assert roles == {"demo"}
    assert paths == {a.resolve(), b.resolve()}


def test_walker_descends_into_submodels(tmp_path: Path) -> None:
    dem = tmp_path / "dem.tif"
    poly = tmp_path / "shed.shp"
    dem.write_text("x")
    poly.write_text("y")

    root = _Root(block=_Block(dem=dem, polygon=poly))
    entries = collect_input_files(root)

    assert {e.role for e in entries} == {"dem", "polygon"}


def test_walker_deduplicates_same_canonical_path(tmp_path: Path) -> None:
    file_path = tmp_path / "dem.tif"
    file_path.write_text("x")
    nested = tmp_path / "sub" / ".." / "dem.tif"

    root = _Root(block=_Block(dem=file_path, sources=[_Source(path=file_path)]))
    entries = collect_input_files(root)
    # Different roles => both preserved.
    assert len(entries) == 2

    root2 = _Root(block=_Block(dem=file_path, polygon=nested))
    # Polygon uses a different role so it is not deduplicated even if the
    # canonical path ends up the same.
    entries2 = collect_input_files(root2)
    assert len(entries2) == 2


def test_walker_preserves_portable_flag(tmp_path: Path) -> None:
    target = tmp_path / "scratch.txt"
    target.write_text("x")

    root = _Root(block=_Block(scratch=target))
    entries = collect_input_files(root)

    assert len(entries) == 1
    assert entries[0].portable is False


def test_walker_ignores_unannotated_fields(tmp_path: Path) -> None:
    class Plain(BaseModel):
        path: Path | None = None

    plain = Plain(path=tmp_path / "ignored.txt")
    assert collect_input_files(plain) == []


def test_walker_handles_string_paths(tmp_path: Path) -> None:
    class Holder(BaseModel):
        src: Annotated[
            str | None,
            InputFile(role="thing", category="data"),
        ] = None

    holder = Holder(src=str(tmp_path / "x"))
    entries = collect_input_files(holder)
    assert len(entries) == 1
    assert entries[0].canonical_path == (tmp_path / "x").resolve()


def test_walker_skips_whitespace_string() -> None:
    class Holder(BaseModel):
        src: Annotated[
            str | None,
            InputFile(role="thing", category="data"),
        ] = None

    holder = Holder(src="   ")
    assert collect_input_files(holder) == []


def test_walker_on_real_hydromodpy_config_annotations() -> None:
    """Geographic config has InputFile markers registered."""
    from hydromodpy.spatial.geographic.geographic_config import GeographicConfig

    meta = [
        (name, field_info.metadata)
        for name, field_info in GeographicConfig.model_fields.items()
    ]
    roles_by_field = {}
    for name, metadata in meta:
        for entry in metadata:
            if isinstance(entry, InputFile):
                roles_by_field[name] = entry.role
    assert roles_by_field == {
        "dem_init_path": "dem",
        "polyg_shp_path": "watershed_polygon",
        "bottom_path": "aquifer_bottom",
    }


def test_walker_on_real_dem_source_annotations() -> None:
    """DEM source config has InputFile on path."""
    from hydromodpy.data.variables.dem.config import DemSourceConfig

    field_info = DemSourceConfig.model_fields["path"]
    markers = [m for m in field_info.metadata if isinstance(m, InputFile)]
    assert len(markers) == 1
    assert markers[0].role == "dem"
    assert markers[0].category == "data"
