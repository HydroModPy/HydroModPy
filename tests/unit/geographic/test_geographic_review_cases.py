"""Unit tests for the geographic visual review launcher."""

from __future__ import annotations

import pytest

from hydromodpy.spatial.geographic.cases.review_cases import (
    available_case_review_names,
    list_case_reviews,
    resolve_case_review_specs,
)


def test_available_case_review_names_exposes_expected_cases() -> None:
    names = available_case_review_names()
    assert "reference_catchment_delineation_case" in names
    assert "reference_river_network_nancon" in names


def test_list_case_reviews_outputs_case_lines() -> None:
    lines: list[str] = []
    list_case_reviews(printer=lines.append)
    assert any("reference_catchment_delineation_case" in line for line in lines)
    assert any("reference_river_network_nancon" in line for line in lines)


def test_resolve_case_review_specs_rejects_unknown_case() -> None:
    with pytest.raises(ValueError, match="Unknown geographic review case"):
        resolve_case_review_specs(["unknown_case"])
