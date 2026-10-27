"""``[mesh.lake_refinement]`` refines the shore band, the structures and maybe the interior.

The table is the switch: an ``enabled`` key is refused and names the table. A
size or a band that would slip between the sampling nodes of the size field is
refused, and so is an interior finer than the shore.
"""

from __future__ import annotations

import pytest

from hydromodpy.spatial.mesh.refinement.lake_refinement import LakeRefinementConfig


@pytest.mark.parametrize(
    ("table", "match"),
    [
        ({"cell_size": 40.0, "interior_size": 20.0}, "interior_size"),
        ({"cell_size": 40.0, "shoreline_band": 5.0}, "shoreline_band"),
        ({"dam_cell_size": 60.0, "hfb_buffer": 10.0}, "hfb_buffer"),
        ({"enabled": True, "cell_size": 40.0}, r"\[mesh\.lake_refinement\] has no 'enabled' key"),
        ({"enabled": False, "cell_size": 40.0}, r"\[mesh\.lake_refinement\] has no 'enabled' key"),
    ],
    ids=[
        "interior finer than the shore",
        "shore band thinner than a cell",
        "wall zone thinner than a dam cell",
        "enabled true",
        "enabled false",
    ],
)
def test_a_lake_refinement_table_that_cannot_hold_its_cells_is_refused(
    table: dict, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        LakeRefinementConfig.model_validate(table)
