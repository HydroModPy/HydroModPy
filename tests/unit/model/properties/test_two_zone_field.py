"""The two-zone square of the field demos, :mod:`hydromodpy.model.properties.two_zone_field`."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.model.properties.two_zone_field import FieldSquare
from tests._helpers.field_cases import write_text

X = np.array([[0.25, 0.75], [0.25, 0.75]])
Y = np.array([[0.25, 0.25], [0.75, 0.75]])
NAMES = {"G": "granite", "M": "micaschists"}


@pytest.mark.parametrize(
    ("config", "side", "zones"),
    [
        ({"line": " Diag_Main"}, [[0.0, -0.5], [0.5, 0.0]], ["GM", "GG"]),
        ({"line_family": "diagonal", "line_orientation": "anti"}, [[-0.5, 0.0], [0.0, 0.5]], ["MG", "GG"]),
        ({"line_family": "axis", "line_orientation": "vertical"}, [[-0.25, 0.25], [-0.25, 0.25]], ["MG", "MG"]),
        ({"line_family": "symmetry_axis", "line_orientation": "horizontal"}, [[-0.25, -0.25], [0.25, 0.25]], ["MM", "GG"]),
        ({"line": "diag_main", "zone1_side": "Negative"}, [[0.0, -0.5], [0.5, 0.0]], ["MG", "MM"]),
    ],
    ids=["main-diagonal", "anti-diagonal", "vertical-axis", "horizontal-axis", "zone1-on-the-negative-side"],
)  # fmt: skip
def test_a_line_splits_the_square_into_its_two_zones(config, side, zones):
    field = FieldSquare.from_dict(config)
    np.testing.assert_allclose(field.signed_side(X, Y), side)
    assert field.zone_id(X, Y).tolist() == [[NAMES[key] for key in row] for row in zones]


def _with_line(line: str) -> FieldSquare:
    field = FieldSquare()
    field.line = line
    return field


@pytest.mark.parametrize(
    ("build", "error", "match"),
    [
        (lambda: FieldSquare(line="spiral"), ValueError, r"line 'spiral'\. Allowed: diag_main, diag_anti, axis_vertical, axis_horizontal$"),
        (lambda: FieldSquare(zone1_side="up"), ValueError, r"zone1_side 'up'\. Allowed: positive, negative$"),
        (lambda: FieldSquare(zone2_name=" "), ValueError, "zone1_name and zone2_name must be non-empty"),
        (lambda: FieldSquare.from_dict(["diag_main"]), TypeError, "config must be a mapping"),
        (lambda: FieldSquare.from_dict({"line_family": "diagonal", "line_orientation": "vertical"}), ValueError, "'main' or 'anti'"),
        (lambda: FieldSquare.from_dict({"line_family": "axis", "line_orientation": "main"}), ValueError, "'vertical' or 'horizontal'"),
        (lambda: FieldSquare.from_dict({"line_family": "circle"}), KeyError, "either 'line' or"),
        (lambda: FieldSquare().signed_side(X, Y[0]), ValueError, "x and y must have the same shape"),
        (lambda: _with_line("spiral").signed_side(X, Y), ValueError, "line 'spiral'$"),
    ],
    ids=["unknown-line", "unknown-side", "blank-zone", "not-a-mapping", "diagonal-not-main-or-anti",
         "axis-not-vertical-or-horizontal", "no-line", "points-of-two-shapes", "line-changed-after-build"],
)  # fmt: skip
def test_a_square_it_cannot_split_is_refused(build, error, match):
    with pytest.raises(error, match=match):
        build()


def test_a_square_reads_its_line_and_zones_from_toml(tmp_path: Path):
    path = write_text(
        tmp_path / "field_geometry.toml",
        '[field]\nid = "field_square"\nline = "axis_vertical"\nzone1_side = "negative"\n'
        'zone1_name = "granite"\nzone2_name = "micaschists"',
    )

    field = FieldSquare.from_toml(path, section="field")

    assert field.as_dict() == {
        "id": "field_square",
        "line": "axis_vertical",
        "zone1_side": "negative",
        "zone1_name": "granite",
        "zone2_name": "micaschists",
    }
