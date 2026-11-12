"""AUTO_FLOW_REDUCE cuts that exceed 10 % of a well are reported, smaller ones are not."""

from __future__ import annotations

import pytest

from hydromodpy.model.sinks_sources.wells import throttled_well_message, throttled_well_report

# MODFLOW 6 LAK reads every lake forcing as zero or more and stops on a negative one.
#
# The lake guide wrote withdrawals as negative values, and nothing flipped the
# sign, so MODFLOW 6 aborted with 'Withdrawal must be positive'.

# AUTO_FLOW_REDUCE cuts that exceed 10 % of a well are reported, smaller ones are not.


@pytest.mark.unit
def test_a_well_cut_to_17_percent_is_reported() -> None:
    rows = throttled_well_report({(0, 4): -756000.0}, {(0, 4): -131858.0})
    assert len(rows) == 1
    assert rows[0]["cut_fraction"] == pytest.approx(1.0 - 131858.0 / 756000.0)
    assert "17 % pumped" in throttled_well_message(rows)


@pytest.mark.unit
def test_a_well_cut_by_less_than_10_percent_is_silent() -> None:
    assert throttled_well_report({(1, 4): -100.0}, {(1, 4): -95.0}) == []
    assert throttled_well_report({(1, 4): -100.0}, {(1, 4): -100.0}) == []
