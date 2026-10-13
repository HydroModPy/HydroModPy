"""What a parameter card shows, from the helpers of the Sphinx extension."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

EXT = Path(__file__).resolve().parents[3] / "docs" / "source" / "_ext"


@pytest.fixture(scope="module")
def H():
    """The Sphinx extensions are modules of docs/source/_ext, not of a package."""
    sys.path.insert(0, str(EXT))
    try:
        import hmp_params
    finally:
        sys.path.remove(str(EXT))
    return hmp_params


def test_the_card_does_not_repeat_the_summary_line(H) -> None:
    n = {"summary": "One sentence.", "description": "One  sentence.\n\nMore text here."}
    assert H.rest_of_description(n) == "More text here."
    assert H.rest_of_description({"summary": "Only.", "description": "Only."}) == ""


def test_a_list_of_fixed_length_reads_exactly(H) -> None:
    assert H.range_text({"min_length": 2, "max_length": 2}) == "exactly 2 items"
    assert H.range_text({"min_length": 1}) == "at least 1 item"
    assert H.range_text({"ge": 0, "le": 1}) == "[0, 1]"


def test_no_explanation_only_when_nothing_explains_the_value(H) -> None:
    n = {
        "literal": ["replace", "scale", "logit"],
        "value_docs": {"scale": "multiplies"},
        "description": "'replace' writes the value as is.",
    }
    assert H.unexplained(n) == {"logit"}
