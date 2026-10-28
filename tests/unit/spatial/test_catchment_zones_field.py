"""A catchment zone field: a code matrix and the label of each code."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.catchment_zones_field import CatchmentZonesField

CODES = np.array([[0, 1], [2, 3]])
LABELS = {1: "riparian", 2: "hillslope", 3: "plateau"}


def test_the_field_snapshot_names_its_zones_in_code_order() -> None:
    field = CatchmentZonesField("zones", CODES, {3: " plateau ", 1: "riparian", 2: "hillslope"},
                                source_meta={"tag": 4})  # fmt: skip

    assert field.zone_keys == ("riparian", "hillslope", "plateau")
    assert field.encoded_codes.dtype == np.uint8
    assert field.as_dict() == {
        "id": "zones",
        "shape": (2, 2),
        "nodata_code": 0,
        "encoded_to_zone": LABELS,
        "zone_keys": ("riparian", "hillslope", "plateau"),
        "source_meta": {"tag": "4"},
    }
    assert CatchmentZonesField("zones", CODES, LABELS).as_dict()["source_meta"] is None


@pytest.mark.parametrize(
    ("codes", "labels", "match"),
    [
        (np.zeros(3), LABELS, "2D array"),
        (np.zeros((0, 2)), LABELS, "cannot be empty"),
        (CODES, {}, "encoded_to_zone cannot be empty"),
        (CODES, {**LABELS, 0: "sea"}, "positive integers"),
        (CODES, {**LABELS, 2: " "}, "labels cannot be empty"),
        (CODES + 1, LABELS, r"unknown class codes: \[4\]"),
    ],
    ids=["not_2d", "empty_codes", "no_label", "zero_code", "blank_label", "unknown_code"],
)
def test_a_code_matrix_its_labels_do_not_describe_is_refused(codes, labels, match) -> None:
    with pytest.raises(ValueError, match=match):
        CatchmentZonesField("zones", codes, labels)
