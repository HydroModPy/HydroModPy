"""AUTO_FLOW_REDUCE cuts that exceed 10 % of a well are reported, smaller ones are not."""

from __future__ import annotations

import pytest

from hydromodpy.physics.flow.sinks_sources.wells import (
    throttled_well_message,
    throttled_well_report,
)
from hydromodpy.solver.modflow6.run import warn_on_throttled_wells

pytestmark = pytest.mark.unit


def test_a_well_cut_to_17_percent_is_reported() -> None:
    rows = throttled_well_report({(0, 4): -756000.0}, {(0, 4): -131858.0})
    assert len(rows) == 1
    assert rows[0]["cut_fraction"] == pytest.approx(1.0 - 131858.0 / 756000.0)
    assert "17 % pumped" in throttled_well_message(rows)


def test_a_well_cut_by_less_than_10_percent_is_silent() -> None:
    assert throttled_well_report({(1, 4): -100.0}, {(1, 4): -95.0}) == []
    assert throttled_well_report({(1, 4): -100.0}, {(1, 4): -100.0}) == []


def test_a_model_without_wells_warns_nothing() -> None:
    class _Model:
        wel = None

    model = _Model()
    assert warn_on_throttled_wells(model) == []
    assert model.well_throttle_report == []
