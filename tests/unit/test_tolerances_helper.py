"""Smoke tests for ``tests/_helpers/tolerances.py``."""

from __future__ import annotations

import pytest

from tests._helpers.tolerances import TOLERANCES, tol


@pytest.mark.fast
def test_tolerances_loads_some_entries() -> None:
    """The markdown table must yield at least a few canonical entries."""
    assert isinstance(TOLERANCES, dict)
    assert len(TOLERANCES) >= 5, TOLERANCES
    for value in TOLERANCES.values():
        assert isinstance(value, float)


@pytest.mark.fast
def test_percent_is_normalised_to_fraction() -> None:
    """A '1 %' cell becomes 0.01 (fraction)."""
    value = tol("global_water_budget_closure")
    assert 0.0 < value <= 1.0
    assert value == pytest.approx(0.01)


@pytest.mark.fast
def test_unique_substring_match() -> None:
    """A unique substring resolves to a single key."""
    value = tol("dupuit_fixed_head_1d_mf6")
    assert value == pytest.approx(0.02)


@pytest.mark.fast
def test_unknown_metric_raises() -> None:
    with pytest.raises(KeyError):
        tol("does_not_exist_anywhere_in_table")
