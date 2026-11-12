"""``[mesh]`` names an engine, sizes in meters and line intentions, and refuses what no engine reads."""

from __future__ import annotations

import types
import typing

import pytest
from pydantic import BaseModel, ValidationError

from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.mesh.engines.voronoi.lloyd import LLOYD_TOLERANCE
from hydromodpy.mesh.mesh_config import (
    MeshConfig,
    MeshFamiliesConfig,
    MeshRegularConfig,
    MeshTriangleConfig,
    MeshVoronoiConfig,
)
from hydromodpy.mesh.request import FAMILY_NAMES

MODELS = (MeshConfig, MeshFamiliesConfig, MeshRegularConfig, MeshTriangleConfig, MeshVoronoiConfig)


def test_lloyd_tolerance_default() -> None:
    assert MeshVoronoiConfig().lloyd_tolerance == LLOYD_TOLERANCE
    config = MeshConfig(engine="voronoi", voronoi={"lloyd_tolerance": 0.05})

    assert config.voronoi.lloyd_tolerance == 0.05


def _leaves(annotation: object) -> list[object]:
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        return _leaves(typing.get_args(annotation)[0])
    if origin in (typing.Union, types.UnionType):
        return [leaf for arg in typing.get_args(annotation) for leaf in _leaves(arg)]
    return [annotation]


@pytest.mark.parametrize("model", MODELS, ids=lambda model: model.__name__)
def test_every_key_is_documented(model: type[BaseModel]) -> None:
    for name, field in model.model_fields.items():
        assert len((field.description or "").split()) >= 6, f"{model.__name__}.{name}"
        assert any(isinstance(meta, Profile) for meta in field.metadata), f"{model.__name__}.{name}"
        extra = field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {}
        leaves = _leaves(field.annotation)
        numeric = any(leaf in (int, float) for leaf in leaves) or name == "shape"
        if numeric:
            assert extra.get("unit"), f"{model.__name__}.{name} declares no unit"
        for leaf in leaves:
            if typing.get_origin(leaf) is typing.Literal:
                values = set(typing.get_args(leaf))
                assert set(extra.get("value_docs", {})) == values, f"{model.__name__}.{name}"


def test_river_trace_needed():
    # The catchment engine ignores the rivers. The triangulated engines read
    # the river networks. The regular engine reads them another way.
    assert not MeshConfig(engine="catchment").requires_river_trace(active_bc=[], synthetic=False)
    assert MeshConfig(engine="triangle").requires_river_trace(active_bc=[], synthetic=False)
    assert not MeshConfig(engine="regular").requires_river_trace(active_bc=[], synthetic=False)


def test_family_names():
    assert frozenset(MeshFamiliesConfig.model_fields) == FAMILY_NAMES


def _refused(data: dict, *words: str) -> None:
    with pytest.raises(ValidationError) as raised:
        MeshConfig.model_validate(data)
    message = str(raised.value)
    for word in words:
        assert word in message, message


@pytest.mark.parametrize(
    ("data", "words"),
    [
        ({"engine": "triangle", "regular": {"shape": [10, 10]}}, ("[mesh.regular]", "triangle")),
        ({"engine": "regular", "regular": {"shape": [10, 10]}, "cell_size": 50.0}, ("cell_size",)),
        ({"engine": "regular", "triangle": {"algorithm": "frontal"}}, ("[mesh.triangle]",)),
        ({"engine": "regular", "triangle": {"path": "a.msh"}}, ("[mesh.triangle]",)),
        ({"engine": "triangle", "voronoi": {"seeds": "generated"}}, ("[mesh.voronoi]",)),
        ({"engine": "voronoi", "voronoi": {"seeds": "triangulation"}}, ("triangulation", "path")),
        (
            {"engine": "voronoi", "triangle": {"path": "a.msh"}, "voronoi": {"seeds": "generated"}},
            ("seeds",),
        ),
        (
            {
                "engine": "voronoi",
                "triangle": {"path": "a.msh"},
                "voronoi": {"lloyd_tolerance": 0.05},
            },
            ("lloyd_tolerance", "triangulation"),
        ),
        (
            {"engine": "voronoi", "voronoi": {"seeds": "triangulation", "lloyd_tolerance": 0.05}},
            ("triangulation", "path"),
        ),
        ({"engine": "triangle", "cell_size": 50.0, "river_cell_size": 80.0}, ("river_cell_size",)),
        ({"lake_refinement": {"enabled": True}}, ("[mesh.lake_refinement]", "'enabled'", "table")),
        ({"lake_refinement": {"enabled": False}}, ("[mesh.lake_refinement]", "'enabled'", "table")),
    ],
)
def test_refusals(data: dict, words: tuple[str, ...]) -> None:
    _refused(data, *words)
