"""``[mesh]`` names an engine, sizes in meters and line intentions, and refuses what no engine reads."""

from __future__ import annotations

import types
import typing

import pytest
from pydantic import BaseModel, ValidationError

from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.mesh.mesh_config import (
    MeshConfig,
    MeshFamiliesConfig,
    MeshRegularConfig,
    MeshTriangleConfig,
    MeshVoronoiConfig,
)

_MODELS = (MeshConfig, MeshFamiliesConfig, MeshRegularConfig, MeshTriangleConfig, MeshVoronoiConfig)


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
def test_a_combination_no_engine_reads_is_refused(data: dict, words: tuple[str, ...]) -> None:
    _refused(data, *words)


def test_the_lloyd_tolerance_of_generated_generators_is_a_dev_key_with_the_engine_default() -> None:
    from hydromodpy.mesh.engines.voronoi.lloyd import LLOYD_TOLERANCE

    assert MeshVoronoiConfig().lloyd_tolerance == LLOYD_TOLERANCE
    config = MeshConfig(engine="voronoi", voronoi={"lloyd_tolerance": 0.05})

    assert config.voronoi.lloyd_tolerance == 0.05


_HAND = {"where": "height_above_stream", "below": 2.0, "cell_size": 20.0}
_NO_RIVERS = {"rivers": "none", "geology": "none", "lakes": "none", "barriers": "none"}


def _leaves(annotation: object) -> list[object]:
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        return _leaves(typing.get_args(annotation)[0])
    if origin in (typing.Union, types.UnionType):
        return [leaf for arg in typing.get_args(annotation) for leaf in _leaves(arg)]
    return [annotation]


@pytest.mark.parametrize("model", _MODELS, ids=lambda model: model.__name__)
def test_every_key_is_documented_for_the_generated_reference(model: type[BaseModel]) -> None:
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


def test_a_mesh_engine_that_ignores_rivers_needs_no_river_trace():
    from hydromodpy.mesh.mesh_config import MeshConfig

    catchment = MeshConfig(engine="catchment")
    triangle = MeshConfig(engine="triangle")
    regular = MeshConfig(engine="regular")
    # The catchment engine ignores the rivers, so the trace is not needed.
    assert not catchment.requires_river_trace(active_bc=[], synthetic=False)
    # The triangulated engines read the river networks, so the trace is needed.
    assert triangle.requires_river_trace(active_bc=[], synthetic=False)
    # The regular engine reads the rivers by another way, so it needs none.
    assert not regular.requires_river_trace(active_bc=[], synthetic=False)


def _engine_for(engine_id):
    from hydromodpy.mesh.registry import mesh_engines

    return mesh_engines.get(engine_id)


def test_the_family_names_are_the_keys_of_mesh_families():
    from hydromodpy.mesh.mesh_config import MeshFamiliesConfig
    from hydromodpy.mesh.request import FAMILY_NAMES

    assert frozenset(MeshFamiliesConfig.model_fields) == FAMILY_NAMES
