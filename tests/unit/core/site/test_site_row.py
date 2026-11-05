"""A site table row round-trips through a plain mapping, in fixed columns."""

from __future__ import annotations

import pytest

from hydromodpy.core.site import SITE_ROW_COLUMNS, SiteRow


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


def test_a_row_round_trips_through_a_mapping() -> None:
    row = SiteRow(
        site="nancon",
        label="Le Nançon à Lécousse",
        gauge="J0014010",
        uri="hubeau:J0014010",
        x_outlet=389285.91,
        y_outlet=6816518.749,
        crs="EPSG:2154",
        tags=("bretagne", "armorican"),
    )
    mapping = row.to_mapping()
    assert list(mapping) == list(SITE_ROW_COLUMNS)
    assert mapping["tags"] == "bretagne;armorican"
    assert SiteRow.from_mapping(mapping) == row


def test_csv_cells_are_read_as_strings() -> None:
    row = SiteRow.from_mapping(
        {"site": "J0170000", "label": "", "x_outlet": "377120.0", "y_outlet": "6831410", "tags": ""}
    )
    assert row.label is None
    assert row.x_outlet == 377120.0
    assert row.tags == ()


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


def test_a_row_is_frozen() -> None:
    row = SiteRow(site="nancon")
    with pytest.raises(AttributeError):
        row.site = "other"  # type: ignore[misc]
