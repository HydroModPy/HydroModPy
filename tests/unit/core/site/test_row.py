"""A site table row round-trips through a plain mapping, in fixed columns."""

from __future__ import annotations

import pytest

from hydromodpy.core.site.row import SITE_ROW_COLUMNS, SiteRow


def test_columns() -> None:
    assert SITE_ROW_COLUMNS == (
        "site",
        "label",
        "gauge",
        "uri",
        "x_outlet",
        "y_outlet",
        "crs",
        "tags",
    )


# One row per bad row: the mapping and the part of the message that names the fix.
REFUSED = [
    pytest.param({"site": "nancon", "k_table": "k.csv"}, "k_table", id="unknown column"),
    pytest.param({"site": "le-nancon"}, "column site", id="bad site name"),
    pytest.param(
        {"site": "nancon", "x_outlet": "east", "y_outlet": "1"}, "column x_outlet", id="bad number"
    ),
    pytest.param({"site": "nancon", "x_outlet": 1.0}, "x_outlet and y_outlet", id="half an outlet"),
]


@pytest.mark.parametrize(("mapping", "match"), REFUSED)
def test_refusals(mapping, match) -> None:
    with pytest.raises(ValueError, match=match):
        SiteRow.from_mapping(mapping)
