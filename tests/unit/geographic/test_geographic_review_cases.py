"""Unit tests for the geographic visual review launcher.

The registry API it shares with the other ``cases/review_cases.py`` modules
is asserted once in ``tests/contract/test_case_review_contract.py``. Only the
names of the shipped geographic cases are pinned here.
"""

from __future__ import annotations

from hydromodpy.spatial.geographic.cases.review_cases import (
    available_case_review_names,
    list_case_reviews,
)


def test_available_case_review_names_exposes_expected_cases() -> None:
    """Both reference cases stay reachable by name from the CLI."""
    names = available_case_review_names()
    assert "reference_catchment_delineation_case" in names
    assert "reference_river_network_nancon" in names


def test_list_case_reviews_outputs_case_lines() -> None:
    """--list shows both reference cases to the operator."""
    lines: list[str] = []
    list_case_reviews(printer=lines.append)
    assert any("reference_catchment_delineation_case" in line for line in lines)
    assert any("reference_river_network_nancon" in line for line in lines)
