"""What a parameter card shows, from the helpers of the Sphinx extension."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "docs" / "source" / "_ext"))

import hmp_params as H  # noqa: E402


def test_the_card_does_not_repeat_the_summary_line() -> None:
    n = {"summary": "One sentence.", "description": "One  sentence.\n\nMore text here."}
    assert H.rest_of_description(n) == "More text here."
    assert H.rest_of_description({"summary": "Only.", "description": "Only."}) == ""


def test_a_list_of_fixed_length_reads_exactly() -> None:
    assert H.range_text({"min_length": 2, "max_length": 2}) == "exactly 2 items"
    assert H.range_text({"min_length": 1}) == "at least 1 item"
    assert H.range_text({"ge": 0, "le": 1}) == "[0, 1]"


def test_no_explanation_only_when_nothing_explains_the_value() -> None:
    n = {
        "literal": ["replace", "scale", "logit"],
        "value_docs": {"scale": "multiplies"},
        "description": "'replace' writes the value as is.",
    }
    assert H.unexplained(n) == {"logit"}
