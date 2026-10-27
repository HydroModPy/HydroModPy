"""A ``[[mesh.refinement_zone]]`` table names a vector layer, or one field and its threshold.

The validators refuse a table that gives both or neither, a threshold the field
does not read, a run where none is read or none where one is, and a corridor
thinner than a cell. A table dumps back to itself, and describes itself in a few
words for the notes and the journal.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.mesh.refinement.refinement_zones import RefinementZoneConfig

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
    ],
)
def test_a_zone_says_one_field_and_its_threshold_or_is_refused(
    table: dict, words: tuple[str, ...]
) -> None:
    with pytest.raises(ValidationError) as raised:
        RefinementZoneConfig.model_validate(table)
    for word in words:
        assert word in str(raised.value)


def test_a_layer_zone_reads_as_it_did_and_a_zone_dumps_back() -> None:
    layer = RefinementZoneConfig.model_validate({"path": "z.gpkg", "cell_size": 20.0})
    criterion = RefinementZoneConfig.model_validate({**_RUN_ZONE, "where": " WaterTable_Depth "})

    assert layer.where is None and layer.below is None and layer.run is None
    assert criterion.where == "watertable_depth"
    for zone in (layer, criterion):
        assert RefinementZoneConfig.model_validate(zone.model_dump()) == zone


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
def test_a_zone_describes_its_field_threshold_unit_and_run(table: dict, description: str) -> None:
    assert RefinementZoneConfig.model_validate(table).describe() == description
