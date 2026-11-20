"""Which fields of a Pydantic config are input files, found and rewritten by the walker.

A relative path resolves under the project base, never under the shell's working
directory, so a project tracks the same files wherever the command is launched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.core.tracking.walker import collect_input_files, rewrite_input_paths


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


class _StringHolder(BaseModel):
    src: Annotated[str | None, InputFile(role="thing", category="data")] = None


def test_string_paths_are_collected(tmp_path: Path) -> None:
    entries = collect_input_files(_StringHolder(src=str(tmp_path / "x")))
    assert [e.canonical_path for e in entries] == [(tmp_path / "x").resolve()]


def test_blank_string_is_skipped() -> None:
    assert collect_input_files(_StringHolder(src="   ")) == []


def test_input_markers_of_the_catchment_configs() -> None:
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


def _file_dem_source():
    from hydromodpy.data.variables.dem.config import FileDemSource

    return FileDemSource


def _file_substratum_source():
    from hydromodpy.data.variables.user_rasters import FileSubstratumSource

    return FileSubstratumSource


@pytest.mark.parametrize(
    ("source", "role", "category"),
    [
        pytest.param(_file_substratum_source, "substratum", "geometry", id="substratum"),
        pytest.param(_file_dem_source, "dem", "data", id="dem"),
    ],
)
def test_data_source_markers(source, role, category) -> None:
    metadata = source().model_fields["path"].metadata
    markers = [m for m in metadata if isinstance(m, InputFile)]
    assert [(m.role, m.category) for m in markers] == [(role, category)]


def test_relative_path_on_base(tmp_path: Path) -> None:
    (tmp_path / "dem.tif").write_text("x")
    root = _Root(block=_Block(dem=Path("dem.tif")))

    (entry,) = collect_input_files(root, base=tmp_path)

    assert entry.canonical_path == (tmp_path / "dem.tif").resolve()
    assert entry.original_path == "dem.tif"


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


UNTOUCHED_PAYLOADS = [
    pytest.param({"dem": ""}, id="empty"),
    pytest.param({"dem": "   "}, id="blank"),
    pytest.param({"dem": None}, id="none"),
    pytest.param({"unknown": "a.tif"}, id="unknown key"),
    pytest.param({"block": None}, id="none table"),
    pytest.param({"stations": ["not-a-table"]}, id="item not a table"),
    pytest.param({"by_name": {"x": "not-a-table"}}, id="value not a table"),
    pytest.param({"label": "a.tif"}, id="unmarked string"),
]


@pytest.mark.parametrize("payload", UNTOUCHED_PAYLOADS)
def test_rewriting_leaves_other_values_alone(payload: dict) -> None:
    before = {k: (dict(v) if isinstance(v, dict) else v) for k, v in payload.items()}

    rewrite_input_paths(payload, _Plan, _upper)

    assert payload == before


class _Streams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    geometry: Annotated[Path | None, InputFile(role="network_map", category="geometry")] = None


def test_relative_path_in_folder(tmp_path: Path) -> None:
    target = tmp_path / "data" / "hydrography" / "streams.gpkg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"only its location matters here")
    config = _Streams(geometry=Path("data/hydrography/streams.gpkg"))

    (entry,) = collect_input_files(config, base=tmp_path)

    assert entry.canonical_path == target.resolve()
