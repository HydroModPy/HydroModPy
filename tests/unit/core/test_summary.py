"""Short summaries: one value on one line, the fields of a dataclass, aligned rows."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from hydromodpy.core.summary import LINE, area_span, extent, members, one_line, summary


@dataclass
class Pair:
    first: object
    second: object = None


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, "none"),
        ({"K": 1, "Sy": 2}, "K, Sy"),
        ({}, "none"),
        (3.5, "3.5"),
        ("a\nb", "'a\\nb'"),
        (Pair(1), "Pair(first=1, second=None)"),
    ],
)
def test_one_line_names_a_mapping_by_its_keys_and_keeps_the_first_line(value, text):
    assert one_line(value) == text


def test_one_line_cuts_a_long_value_and_names_a_missing_one():
    cut = one_line("x" * 300)
    assert len(cut) == LINE and cut.endswith(" ...")
    assert one_line(None, "not built yet") == "not built yet"


def test_the_box_and_the_areas_of_a_mesh_are_said_in_metres():
    points = np.array([[10.0, 5.0], [30.4, 25.0], [20.0, 15.0]])
    assert extent(points) == "x 10 to 30 m, y 5 to 25 m"
    assert area_span(np.array([2.5e5, 7.5e5])) == "array (2,), 250000 to 750000 m2, 1.00 km2 in all"


def test_a_summary_aligns_one_row_per_member():
    rows = members(Pair({"a": 1}), "not built yet")
    assert rows == [("first", "a"), ("second", "not built yet")]
    assert summary("Pair", rows).splitlines() == ["Pair", "  first   a", "  second  not built yet"]
    assert summary("Empty", []) == "Empty"
