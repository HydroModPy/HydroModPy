"""A reader asks for a series by one name; a table stores its variable and its source."""

from __future__ import annotations

import pytest

from hydromodpy.core.scope import OBSERVED, SIMULATED, series_name, series_selector


@pytest.mark.parametrize(
    ("name", "variable", "source"),
    [("discharge", "discharge", SIMULATED), ("discharge_obs", "discharge", OBSERVED)],
)
def test_a_name_says_a_variable_and_a_source(name: str, variable: str, source: str) -> None:
    assert series_selector(name) == (variable, source)
    assert series_name(variable, source) == name
