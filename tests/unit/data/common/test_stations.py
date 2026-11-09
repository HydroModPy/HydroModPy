"""Unit tests for hydromodpy.data.common.stations."""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import DataSourceError
from hydromodpy.data.common.stations import report_dropped


def test_report_dropped_empty():
    # When dropped is empty, no-op
    report_dropped("hydrometry", "hubeau", named=["A"], dropped=[], kept=["A"], reason="test")


def test_report_dropped_partial_named():
    with pytest.warns(UserWarning, match="1 station.*dropped.*no records"):
        report_dropped(
            "hydrometry",
            "hubeau",
            named=["A", "B"],
            dropped=["A"],
            kept=["B"],
            reason="no records",
            product="QIXM",
        )


def test_report_dropped_all_named_raises():
    with pytest.raises(DataSourceError, match="every named station of source 'hubeau' was dropped"):
        report_dropped(
            "hydrometry",
            "hubeau",
            named=["A", "B"],
            dropped=["A", "B"],
            kept=[],
            reason="no records",
            product="QIXM",
            raise_on_empty=True,
        )


def test_report_dropped_all_named_no_raise_when_disabled():
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


def test_report_dropped_search_dropped_all_warns_only():
    # For a geographic search where named is None or empty, dropping all does not raise DataSourceError
    with pytest.warns(UserWarning, match="No station of the search lies inside"):
        report_dropped(
            "hydrometry",
            "hubeau",
            named=None,
            dropped=["A", "B"],
            kept=[],
            reason="outside extent",
        )
