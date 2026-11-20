"""Report of the stations a source dropped: a warning, and an error when nothing is left."""

from __future__ import annotations

import pytest

from hydromodpy.data.common.stations import report_dropped


def test_nothing_dropped_is_silent():
    report_dropped("hydrometry", "hubeau", named=["A"], dropped=[], kept=["A"], reason="test")


def test_all_named_stations_dropped_warns_when_not_raising():
    with pytest.warns(
        UserWarning, match="every named station of source 'hubeau' was dropped|2 station.*dropped"
    ):
        report_dropped(
            "hydrometry",
            "hubeau",
            named=["A", "B"],
            dropped=["A", "B"],
            kept=[],
            reason="no records",
            raise_on_empty=False,
        )


def test_a_search_that_drops_everything_only_warns():
    # A geographic search names no station, so it never raises DataSourceError.
    with pytest.warns(UserWarning, match="No station of the search lies inside"):
        report_dropped(
            "hydrometry",
            "hubeau",
            named=None,
            dropped=["A", "B"],
            kept=[],
            reason="outside extent",
        )
