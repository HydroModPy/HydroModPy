"""The two-zone square of the field demos, :mod:`hydromodpy.spatial.field.two_zone_field`."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.spatial.field.two_zone_field import FieldSquare
from tests._helpers.field_cases import write_text

X = np.array([[0.25, 0.75], [0.25, 0.75]])
Y = np.array([[0.25, 0.25], [0.75, 0.75]])


def test_a_line_named_by_its_family_and_orientation_splits_the_square():
    field = FieldSquare.from_dict(
        {
            "id": "field_square",
            "line_family": "symmetry_axis",
            "line_orientation": "horizontal",
            "zone1_side": "positive",
            "zone1_name": "granite",
            "zone2_name": "micaschists",
        }
    )

    zones = field.zone_id(X, Y)

    assert zones.shape == (2, 2)
    assert set(np.unique(zones).tolist()) <= {"granite", "micaschists"}


def test_a_square_reads_its_line_and_zones_from_toml(tmp_path: Path):
    path = write_text(
        tmp_path / "field_geometry.toml",
        """
        [field]
        id = "field_square"
        line = "axis_vertical"
        zone1_side = "negative"
        zone1_name = "granite"
        zone2_name = "micaschists"
        """,
    )

    field = FieldSquare.from_toml(path, section="field")

    assert field.identifier == "field_square"
    assert field.line == "axis_vertical"
    assert field.zone1_side == "negative"
    assert (field.zone1_name, field.zone2_name) == ("granite", "micaschists")
