"""A site table row round-trips through a plain mapping, in fixed columns."""

from __future__ import annotations

import pytest

from hydromodpy.core.site.row import SITE_ROW_COLUMNS, SiteRow


def test_the_columns_are_fixed_and_ordered() -> None:
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


def test_an_unknown_column_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="k_table"):
        SiteRow.from_mapping({"site": "nancon", "k_table": "k.csv"})


def test_a_bad_site_name_is_refused() -> None:
    with pytest.raises(ValueError, match="column site"):
        SiteRow(site="le-nancon")


def test_a_bad_number_names_its_column() -> None:
    with pytest.raises(ValueError, match="column x_outlet"):
        SiteRow.from_mapping({"site": "nancon", "x_outlet": "east", "y_outlet": "1"})


def test_half_an_outlet_is_refused() -> None:
    with pytest.raises(ValueError, match="x_outlet and y_outlet"):
        SiteRow(site="nancon", x_outlet=1.0)
