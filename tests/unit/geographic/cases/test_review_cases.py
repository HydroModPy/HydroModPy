"""The names of the shipped geographic cases; the shared registry API is in the contract tests."""

from hydromodpy.spatial.geographic.cases.review_cases import (
    available_case_review_names,
    list_case_reviews,
)

CASES = ("reference_catchment_delineation_case", "reference_river_network_nancon")


def test_both_reference_cases_are_reachable_by_name_and_listed() -> None:
    lines: list[str] = []
    list_case_reviews(printer=lines.append)
    for case in CASES:
        assert case in available_case_review_names()
        assert any(case in line for line in lines)
