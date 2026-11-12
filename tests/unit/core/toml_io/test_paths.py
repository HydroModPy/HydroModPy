"""Dotted key paths (--set, HMP_SET_*, bind, inline recipes) and declared file paths.

A dotted path names a key inside nested tables, with quotes around a part that
holds dots. A declared file path is written relative to the project root, so a
run frozen in one workspace resolves to the same file in another.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import pytest
from pydantic import BaseModel, Field

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.toml_io.paths import (
    DottedPath,
    UnknownPathError,
    assign,
    former_bare_name_location,
    parse,
    portable_declared_path,
    resolve_field,
)

QUOTED_PARTS = [
    pytest.param('sites.recipes."k2e-5".file', ("sites", "recipes", "k2e-5", "file"), id="dash"),
    pytest.param("a.'x.y'.b", ("a", "x.y", "b"), id="single quotes hold a dot"),
    pytest.param('a."say \\"hi\\"".b', ("a", 'say "hi"', "b"), id="escaped quote"),
    pytest.param(' a . "b c" ', ("a", "b c"), id="spaces around parts"),
    pytest.param('a."x[0]"', ("a", "x[0]"), id="bracket in quotes"),
]


@pytest.mark.parametrize(("text", "parts"), QUOTED_PARTS)
def test_parse(text, parts):
    assert parse(text).parts == parts


def test_path_round_trip():
    path = DottedPath(("sites", "recipes", "k2e-5", "a.b", "plain", "x y"))
    assert str(path) == 'sites.recipes."k2e-5"."a.b".plain."x y"'
    assert parse(str(path)) == path


def test_assign_creates_the_nested_tables():
    payload: dict[str, Any] = {"flow": {"param": {"K": {"type": "homogeneous"}}}}
    assign(payload, "flow.param.K.field.value", 2e-5)
    assign(payload, parse('sites.recipes."k2e-5"'), "k.toml")
    assert payload["flow"]["param"]["K"] == {"type": "homogeneous", "field": {"value": 2e-5}}
    assert payload["sites"]["recipes"]["k2e-5"] == "k.toml"


class Leaf(BaseModel):
    value: float = 0.0
    unit: str = "m/s"


class VariantA(BaseModel):
    kind: str = "a"
    alpha: int = 0


class VariantB(BaseModel):
    kind: str = "b"
    beta: Leaf = Field(default_factory=Leaf)


class Root(BaseModel):
    name: str = ""
    leaf: Leaf | None = None
    variant: Annotated[VariantA | VariantB, Field(discriminator=None)] = Field(
        default_factory=VariantA
    )
    params: dict[str, Leaf] = Field(default_factory=dict)
    free: dict[str, Any] = Field(default_factory=dict)
    items: list[Leaf] = Field(default_factory=list)


def test_resolve_table_key():
    assert resolve_field(Root, "params.K.value").annotation is float
    assert resolve_field(Root, 'params."k-2".unit').annotation is str


def test_free_table_ends_walk():
    assert resolve_field(Root, "free.any.depth") is Root.model_fields["free"]
    assert resolve_field(Root, "items") is Root.model_fields["items"]
    assert resolve_field(Root, "items__merge") is Root.model_fields["items"]


def test_resolve_project_field():
    field = resolve_field(HydroModPyConfig, "geographic.catchment.x_outlet")
    assert "outlet" in (field.description or "")


MALFORMED_PATHS = ["", "a..b", ".a", "a.", 'a.""', "a b", "a.$b", 'a."open']

# (root, path, the part of the message that names the problem)
UNKNOWN_PATHS = [
    pytest.param(Root, "items.value", "items is a list", id="below a list"),
    pytest.param(Root, "leaf.valeu", "nearest: value", id="typo names its neighbours"),
    pytest.param(Root, "name.first", "name is a value", id="below a value"),
    pytest.param(
        HydroModPyConfig, "data.hydrometry.sources.path", "sources is a list", id="project config"
    ),
]


def test_assign_below_a_value():
    with pytest.raises(ValueError, match="simulation.name holds a value"):
        assign({"simulation": {"name": "x"}}, "simulation.name.first", "y")


@pytest.mark.parametrize("text", MALFORMED_PATHS)
def test_malformed_path_refusals(text):
    with pytest.raises(ValueError):
        parse(text)


@pytest.mark.parametrize(("root", "path", "message"), UNKNOWN_PATHS)
def test_unknown_path_refusals(root, path, message):
    with pytest.raises(UnknownPathError, match=message):
        resolve_field(root, path)


def build_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "ws"
    project = workspace / "projects" / "nancon"
    project.mkdir(parents=True)
    for relative in (
        "data/dem/DEM_armorican_massif.tif",
        "data/hydrography/nancon_stream_network.gpkg",
        "data/geology/map.gpkg",
    ):
        (workspace / relative).parent.mkdir(parents=True, exist_ok=True)
        (workspace / relative).write_bytes(b"x")
    (workspace / "data" / "hydrometry").mkdir(parents=True)
    (project / "inputs").mkdir()
    (project / "inputs" / "zones.shp").write_bytes(b"x")
    return workspace, project


def test_portable_declared_path(tmp_path):
    workspace, project = build_workspace(tmp_path)
    outside = tmp_path / "shared" / "dem.tif"
    data = workspace / "data"

    written = portable_declared_path(outside, role="dem", project_root=project, data_dir=data)
    kept = portable_declared_path("inputs/DEM.tif", role="dem", project_root=project, data_dir=data)

    assert written == str(outside.resolve())
    assert kept == "inputs/DEM.tif"  # a relative value is kept as written


def test_former_bare_name_location(tmp_path):
    workspace, _ = build_workspace(tmp_path)
    data = workspace / "data"

    found = former_bare_name_location("DEM_armorican_massif.tif", data, role="dem")
    assert found == (data / "dem" / "DEM_armorican_massif.tif").resolve()
    in_data = former_bare_name_location("map.gpkg", data / "geology")
    assert in_data == (data / "geology" / "map.gpkg").resolve()
    assert former_bare_name_location("map.gpkg", data, role="other") is None
    assert former_bare_name_location("absent.tif", data, role="dem") is None
