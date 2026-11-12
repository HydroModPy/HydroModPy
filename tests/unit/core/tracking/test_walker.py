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
