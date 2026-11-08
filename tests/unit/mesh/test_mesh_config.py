"""``[mesh]`` names an engine, sizes in meters and line intentions, and refuses what no engine reads."""

from __future__ import annotations

import types
import typing

import pytest
from pydantic import BaseModel, ValidationError

from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.mesh import registry
from hydromodpy.mesh.mesh_config import (
    MeshConfig,
    MeshFamiliesConfig,
    MeshRegularConfig,
    MeshTriangleConfig,
    MeshVoronoiConfig,
)
from hydromodpy.mesh.refinement_config import LakeRefinementConfig
from tests._helpers.fake_engines import fake_engine

_MODELS = (MeshConfig, MeshFamiliesConfig, MeshRegularConfig, MeshTriangleConfig, MeshVoronoiConfig)


def _refused(data: dict, *words: str) -> None:
    with pytest.raises(ValidationError) as raised:
        MeshConfig.model_validate(data)
    message = str(raised.value)
    for word in words:
        assert word in message, message


def test_no_section_means_the_regular_engine_on_the_dem_pixels() -> None:
    config = MeshConfig()

    assert config.engine == registry.DEFAULT_ENGINE_ID == "regular"
    assert config.cell_size is None
    assert config.families == MeshFamiliesConfig()
    assert (config.triangle, config.voronoi, config.regular, config.lake_refinement) == (None,) * 4
    assert (config.seed, config.outside_factor, config.transition_distance, config.max_slope) == (
        0,
        2.0,
        500.0,
        0.5,
    )


def test_the_family_defaults_mesh_rivers_as_cells_and_contacts_as_faces() -> None:
    families = MeshFamiliesConfig()

    assert (
        families.rivers,
        families.geology,
        families.lakes,
        families.barriers,
        families.watershed_boundary,
    ) == ("cell", "face", "face", "face", "none")


def test_a_full_user_section_is_read() -> None:
    config = MeshConfig.model_validate(
        {
            "engine": "voronoi",
            "cell_size": 150.0,
            "river_cell_size": 25.0,
            "river_band": 300.0,
            "families": {"geology": "None", "watershed_boundary": "face"},
            "refinement_zone": [{"path": "zones.gpkg", "cell_size": 20.0}],
            "lake_refinement": {"cell_size": 40.0, "shoreline_band": 80.0},
            "outside_factor": 2.0,
            "transition_distance": 500.0,
        }
    )

    assert config.families.geology == "none"
    assert config.refinement_zone[0].cell_size == 20.0
    assert config.lake_refinement is not None and config.lake_refinement.cell_size == 40.0


def test_a_mesh_read_from_a_file_feeds_the_voronoi_generators() -> None:
    config = MeshConfig.model_validate(
        {
            "engine": "voronoi",
            "triangle": {"path": "mesh/d2_frozen/mesh_catchment.msh"},
        }
    )

    assert str(config.triangle.path) == "mesh/d2_frozen/mesh_catchment.msh"
    assert config.voronoi is None


def test_a_regular_grid_takes_its_shape() -> None:
    config = MeshConfig.model_validate({"engine": "regular", "regular": {"shape": [60, 80]}})

    assert config.regular.shape == (60, 80)


def test_the_dump_of_a_section_validates_again() -> None:
    config = MeshConfig.model_validate(
        {
            "engine": "triangle",
            "cell_size": 100.0,
            "triangle": {"algorithm": "frontal"},
            "lake_refinement": {"cell_size": 30.0},
        }
    )

    assert MeshConfig.model_validate(config.model_dump(mode="json")) == config


def test_an_unknown_engine_is_refused_naming_what_is_served() -> None:
    _refused(
        {"engine": "quadtree"},
        "mesh.engine names 'quadtree', and this installation serves",
        "regular",
        "triangle",
        "voronoi",
        registry.ENTRY_POINT_GROUP,
    )


def test_an_installed_engine_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    plugin = fake_engine(
        "test-plugin", engine_version="0.1.0", exact_faces=True, cell_families="exact"
    )
    monkeypatch.setattr(registry.mesh_engines, "classes", dict(registry.mesh_engines.classes))
    monkeypatch.setattr(registry.mesh_engines, "plugins_loaded", True)
    registry.mesh_engines.register(plugin)

    assert MeshConfig(engine="test-plugin").engine == "test-plugin"


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


@pytest.mark.parametrize(
    "data",
    [
        {"constraints_mode": "rivers_only"},
        {"engine": "triangle", "triangle": {"mesh_path": "a.msh"}},
        {"engine": "voronoi", "voronoi": {"lloyd_iterations": 10}},
        {"engine": "regular", "regular": {"nx": 10, "ny": 10}},
        {"families": {"rivers": "face"}},
        {"triangle": {"algorithm": "hxt"}, "engine": "triangle"},
        {"cell_size": 0.0},
        {"river_band": -1.0, "engine": "triangle"},
        {"regular": {"shape": [0, 10]}},
        {"regular": {"shape": [3]}},
        {"regular": {"shape": [3.5, 4]}},
        {"regular": {"shape": "33"}},
        {"outside_factor": 0.5},
        {"transition_distance": -1.0},
        {"max_slope": 0.0},
        {"seed": -1},
        {"voronoi": {"lloyd_tolerance": 0.0}, "engine": "voronoi"},
        {"voronoi": {"seeds": "lloyd"}, "engine": "voronoi"},
        {"river_band": float("inf"), "engine": "triangle"},
        {"river_cell_size": float("inf"), "engine": "triangle"},
        {"outside_factor": float("inf")},
        {"transition_distance": float("inf")},
        {"gap_cells": float("inf"), "engine": "voronoi"},
    ],
)
def test_an_unknown_key_or_a_value_out_of_range_is_refused(data: dict) -> None:
    with pytest.raises(ValidationError):
        MeshConfig.model_validate(data)


def test_the_lloyd_tolerance_of_generated_generators_is_a_dev_key_with_the_engine_default() -> None:
    from hydromodpy.mesh.engines.voronoi.lloyd import LLOYD_TOLERANCE

    assert MeshVoronoiConfig().lloyd_tolerance == LLOYD_TOLERANCE
    config = MeshConfig(engine="voronoi", voronoi={"lloyd_tolerance": 0.05})

    assert config.voronoi.lloyd_tolerance == 0.05


def test_the_lake_refinement_table_is_its_own_switch_and_the_dump_has_no_enabled_key() -> None:
    config = MeshConfig(lake_refinement=LakeRefinementConfig(cell_size=30.0))

    assert config.lake_refinement is not None
    assert "enabled" not in config.model_dump(mode="json")["lake_refinement"]


_HAND = {"where": "height_above_stream", "below": 2.0, "cell_size": 20.0}
_NO_RIVERS = {"rivers": "none", "geology": "none", "lakes": "none", "barriers": "none"}


@pytest.mark.parametrize(
    ("data", "active_bc", "synthetic", "expected"),
    [
        ({}, {"stream"}, False, False),
        ({"engine": "regular", "regular": {"shape": [5, 5]}}, {"stream"}, False, False),
        ({"engine": "triangle"}, set(), False, True),
        ({"engine": "voronoi"}, set(), False, True),
        ({"engine": "voronoi"}, set(), True, False),
        ({"engine": "triangle", "families": {"rivers": "none"}}, {"stream"}, False, False),
        ({"engine": "triangle", "triangle": {"path": "a.msh"}}, set(), False, False),
        ({"engine": "triangle", "triangle": {"path": "a.msh"}}, {"stream", "chd"}, False, True),
        (
            {
                "engine": "voronoi",
                "triangle": {"path": "a.msh"},
                "voronoi": {"seeds": "triangulation"},
            },
            {"stream"},
            True,
            False,
        ),
        ({"engine": "triangle", "triangle": {"algorithm": "frontal"}}, set(), False, True),
        (
            {"engine": "voronoi", "families": _NO_RIVERS, "refinement_zone": [_HAND]},
            set(),
            False,
            True,
        ),
        ({"engine": "voronoi", "families": _NO_RIVERS}, set(), False, False),
        ({"engine": "regular", "refinement_zone": [_HAND]}, set(), False, False),
    ],
)
def test_one_rule_says_when_the_mesh_needs_the_river_trace(
    data: dict, active_bc: set[str], synthetic: bool, expected: bool
) -> None:
    config = MeshConfig.model_validate(data)

    assert config.requires_river_trace(active_bc=active_bc, synthetic=synthetic) is expected


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
