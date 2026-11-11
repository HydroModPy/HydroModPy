"""Walker tests on small synthetic Pydantic models."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.core.tracking.walker import collect_input_files


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
    from hydromodpy.catchment.preprocess.catchment_config import OutletCatchDef, PolygonCatchDef
    from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig

    def _collect_roles(model_cls) -> dict[str, str]:
        roles: dict[str, str] = {}
        for name, field_info in model_cls.model_fields.items():
            for entry in field_info.metadata:
                if isinstance(entry, InputFile):
                    roles[name] = entry.role
        return roles

    geographic_roles = _collect_roles(GeographicConfig)
    outlet_roles = _collect_roles(OutletCatchDef)
    polygon_roles = _collect_roles(PolygonCatchDef)

    # The substratum raster is tracked by [data.substratum], not by [geographic].
    assert geographic_roles == {}
    # The regional DEM is a [[data.dem.sources]] file, tracked by its source.
    assert outlet_roles == {}
    assert polygon_roles == {"polyg_shp_path": "watershed_polygon"}


def test_walker_on_real_substratum_source_annotations() -> None:
    """The substratum raster is tracked as geometry under its own role."""
    from hydromodpy.data.variables.user_rasters import FileSubstratumSource

    field_info = FileSubstratumSource.model_fields["path"]
    markers = [m for m in field_info.metadata if isinstance(m, InputFile)]
    assert len(markers) == 1
    assert markers[0].role == "substratum"
    assert markers[0].category == "geometry"


def test_walker_on_real_dem_source_annotations() -> None:
    """DEM file source config has InputFile on path."""
    from hydromodpy.data.variables.dem.config import FileDemSource

    field_info = FileDemSource.model_fields["path"]
    markers = [m for m in field_info.metadata if isinstance(m, InputFile)]
    assert len(markers) == 1
    assert markers[0].role == "dem"
    assert markers[0].category == "data"


# ------------------------------------------------- relative paths and rewriting

from hydromodpy.core.tracking.walker import rewrite_input_paths  # noqa: E402


def test_a_relative_path_is_anchored_on_base_when_the_file_is_there(tmp_path: Path) -> None:
    (tmp_path / "dem.tif").write_text("x")
    root = _Root(block=_Block(dem=Path("dem.tif")))

    (entry,) = collect_input_files(root, base=tmp_path)

    assert entry.canonical_path == (tmp_path / "dem.tif").resolve()
    assert entry.original_path == "dem.tif"


def test_a_relative_path_missing_under_base_falls_back_to_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "project"
    base.mkdir()
    monkeypatch.chdir(tmp_path)
    root = _Root(block=_Block(dem=Path("ghost.tif")))

    (entry,) = collect_input_files(root, base=base)

    assert entry.canonical_path == (tmp_path / "ghost.tif").resolve()


def test_a_dict_of_models_is_walked_like_a_list() -> None:
    class _Holder(BaseModel):
        tables: dict[str, _Source] = Field(default_factory=dict)

    holder = _Holder(
        tables={"a": _Source(path=Path("/data/a.csv")), "b": _Source(path=Path("/data/b.csv"))}
    )

    assert sorted(e.original_path for e in collect_input_files(holder)) == [
        "/data/a.csv",
        "/data/b.csv",
    ]


class _Station(BaseModel):
    file: Annotated[str | None, InputFile(role="station", category="data")] = None


class _Plan(BaseModel):
    dem: Annotated[str | None, InputFile(role="dem", category="data")] = None
    block: _Block | None = None
    stations: list[_Station] = Field(default_factory=list)
    by_name: dict[str, _Station] = Field(default_factory=dict)
    other: _Station | _Source | None = None
    label: str = "x"


def _upper(marker: InputFile, value: str) -> str:
    return f"{marker.role}:{value}"


def test_rewriting_replaces_every_input_path_of_a_config_document_in_place() -> None:
    payload = {
        "dem": "a.tif",
        "block": {"dem": "b.tif", "sources": [{"path": "c.csv"}, {"path": "d.csv"}]},
        "stations": [{"file": "s1.csv"}, {"file": "s2.csv"}],
        "by_name": {"x": {"file": "s3.csv"}},
        "other": {"path": "u.csv"},
        "label": "untouched",
    }

    rewrite_input_paths(payload, _Plan, _upper)

    assert payload == {
        "dem": "dem:a.tif",
        "block": {"dem": "dem:b.tif", "sources": [{"path": "demo:c.csv"}, {"path": "demo:d.csv"}]},
        "stations": [{"file": "station:s1.csv"}, {"file": "station:s2.csv"}],
        "by_name": {"x": {"file": "station:s3.csv"}},
        "other": {"path": "demo:u.csv"},
        "label": "untouched",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"dem": ""},
        {"dem": "   "},
        {"dem": None},
        {"unknown": "a.tif"},
        {"block": None},
        {"stations": ["not-a-table"]},
        {"by_name": {"x": "not-a-table"}},
        {"label": "a.tif"},
    ],
    ids=[
        "empty",
        "blank",
        "none",
        "unknown-key",
        "none-table",
        "non-dict-item",
        "non-dict-value",
        "plain-str",
    ],
)
def test_rewriting_leaves_empty_unknown_and_unmarked_values_alone(payload: dict) -> None:
    before = {k: (dict(v) if isinstance(v, dict) else v) for k, v in payload.items()}

    rewrite_input_paths(payload, _Plan, _upper)

    assert payload == before
