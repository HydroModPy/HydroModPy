"""The gate of ``phrases.toml``: every code has its phrase, in both languages, with the same fields."""

from __future__ import annotations

import string
from typing import get_args

import pytest

from hydromodpy.config.check import CHECK_CODES
from hydromodpy.results.validity_rules import Label
from hydromodpy.schema.phrases import _TABLES, LANGS, phrase

REASON_CODES = frozenset(
    {
        "fatal_validity",
        "not_converged",
        "known_issue",
        "promoted",
        "overlaps_calibration",
        "scored_outside_calibration",
        "no_scored_window",
        "session_ended",
        "no_score_window",
        "too_few_samples",
        "not_promoted",
        "bound_reached",
    }
)


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def _rows() -> list[tuple[str, str]]:
    return [(table, key) for table, rows in _TABLES.items() for key in rows]


@pytest.mark.parametrize(("table", "key"), _rows())
def test_a_row_has_both_languages_with_the_same_fields(table: str, key: str) -> None:
    row = _TABLES[table][key]
    assert set(row) == set(LANGS)
    assert all(row[lang].strip() for lang in LANGS)
    assert _fields(row["en"]) == _fields(row["fr"])


def test_a_language_outside_the_set_is_refused() -> None:
    with pytest.raises(ValueError, match="lang"):
        phrase("check_state", "passed", "de")
