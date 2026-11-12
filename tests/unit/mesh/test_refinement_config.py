"""The two refinement tables, ``[mesh.lake_refinement]`` and ``[[mesh.refinement_zone]]``.

A ``[[mesh.refinement_zone]]`` table names a vector layer, or one field and its
threshold. The validators refuse a table that gives both or neither, a threshold
the field does not read, a run where none is read or none where one is, and a
corridor thinner than a cell. A table dumps back to itself, and describes itself
in a few words for the notes and the journal.

``[mesh.lake_refinement]`` refines the shore band, the structures and maybe the
interior. The table is the switch: an ``enabled`` key is refused and names the
table. A size or a band that would slip between the sampling nodes of the size
field is refused, and so is an interior finer than the shore. In both tables a
size of zero and an infinite number are refused, with the key.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.mesh.refinement_config import LakeRefinementConfig, RefinementZoneConfig

_HAND = {"where": "height_above_stream", "below": 2.0, "cell_size": 20.0}
_RUN_ZONE = {"where": "watertable_depth", "below": 1.0, "run": "coarse", "cell_size": 20.0}


@pytest.mark.parametrize(
    ("table", "words"),
    [
        ({"cell_size": 20.0}, ("either path", "where")),
        ({"path": "z.gpkg", **_HAND}, ("exactly one",)),
        ({**_HAND, "below": 0.0}, ("below", "greater than 0")),
        ({**_HAND, "below": -1.0}, ("greater than 0",)),
        ({"where": "height_above_stream", "above": 1.0, "cell_size": 20.0}, ("give below",)),
        ({**_HAND, "run": "coarse"}, ("reads no run",)),
        ({"where": "seepage", "above": 0.5, "cell_size": 20.0}, ("name it with run",)),
        ({**_RUN_ZONE, "above": 2.0}, ("not both",)),
        ({"where": "watertable_depth", "run": "coarse", "cell_size": 20.0}, ("one threshold",)),
        ({"path": "z.gpkg", "below": 1.0, "cell_size": 20.0}, ("drop below",)),
        ({"where": "slope", "below": 1.0, "cell_size": 20.0}, ("where",)),
        ({**_HAND, "radius": 3.0}, ("radius",)),
        ({"path": "z.gpkg", "cell_size": 40.0, "radius": 10.0}, ("radius",)),
        ({"path": "z.gpkg", "cell_size": 40.0, "buffer": 10.0}, ("buffer must be >= cell_size",)),
        ({"path": "z.gpkg", "cell_size": 0.0}, ("cell_size", "greater than 0")),
        ({"path": "z.gpkg", "cell_size": float("inf")}, ("cell_size", "finite number")),
        ({**_HAND, "below": float("inf")}, ("below", "finite number")),
    ],
)
def test_zone_refusals(table: dict, words: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError) as raised:
        RefinementZoneConfig.model_validate(table)
    for word in words:
        assert word in str(raised.value)


@pytest.mark.parametrize(
    ("table", "description"),
    [
        ({"path": "z.gpkg", "cell_size": 20.0}, "layer z.gpkg"),
        (_HAND, "height_above_stream below 2 m"),
        (_RUN_ZONE, "watertable_depth below 1 m in run coarse"),
        (
            {"where": "seepage", "above": 0.5, "run": "coarse", "cell_size": 20.0},
            "seepage above 0.5 mm/d in run coarse",
        ),
    ],
)
def test_zone_description(table: dict, description: str) -> None:
    assert RefinementZoneConfig.model_validate(table).describe() == description


@pytest.mark.parametrize(
    ("table", "match"),
    [
        ({"cell_size": 40.0, "interior_size": 20.0}, "interior_size"),
        ({"cell_size": 40.0, "shoreline_band": 5.0}, "shoreline_band"),
        ({"dam_cell_size": 60.0, "hfb_buffer": 10.0}, "hfb_buffer"),
        ({"enabled": True, "cell_size": 40.0}, r"\[mesh\.lake_refinement\] has no 'enabled' key"),
        ({"enabled": False, "cell_size": 40.0}, r"\[mesh\.lake_refinement\] has no 'enabled' key"),
        ({"cell_size": 0.0}, r"cell_size\n.*greater than 0"),
        ({"dam_buffer": float("inf")}, r"dam_buffer\n.*finite number"),
        ({"cell_size": 40.0, "interior_size": float("inf")}, r"interior_size\n.*finite number"),
    ],
    ids=[
        "interior finer than the shore",
        "shore band thinner than a cell",
        "wall zone thinner than a dam cell",
        "enabled true",
        "enabled false",
        "cell size of zero",
        "infinite dam buffer",
        "infinite interior size",
    ],
)
def test_lake_refinement_refusals(table: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        LakeRefinementConfig.model_validate(table)
