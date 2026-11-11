"""The gate of ``phrases.toml``: every code has its phrase, in both languages, with the same fields."""

from __future__ import annotations

import string
from typing import get_args

import pytest

from hydromodpy.config.check import CHECK_CODES
from hydromodpy.results.validity_rules import Label
from hydromodpy.schema.phrases import _TABLES, LANGS, keys, phrase

LABEL_VALUES = frozenset(get_args(Label)[1].words)
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
CHECK_STATES = frozenset({"passed", "failed", "unknown"})

CLOSED = {
    "check": CHECK_CODES,
    "label": LABEL_VALUES,
    "label_reason": REASON_CODES,
    "check_state": CHECK_STATES,
}


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def _rows() -> list[tuple[str, str]]:
    return [(table, key) for table, rows in _TABLES.items() for key in rows]


@pytest.mark.parametrize("table", sorted(_TABLES))
def test_a_table_has_exactly_the_keys_of_its_set(table: str) -> None:
    if table in CLOSED:
        assert keys(table) == CLOSED[table]
    else:
        assert keys(table)


@pytest.mark.parametrize(("table", "key"), _rows())
def test_a_row_has_both_languages_with_the_same_fields(table: str, key: str) -> None:
    row = _TABLES[table][key]
    assert set(row) == set(LANGS)
    assert all(row[lang].strip() for lang in LANGS)
    assert _fields(row["en"]) == _fields(row["fr"])


@pytest.mark.parametrize(("table", "key"), _rows())
def test_a_phrase_fills_its_fields(table: str, key: str) -> None:
    values = {name: "x" for name in _fields(_TABLES[table][key]["en"])}
    for lang in LANGS:
        text = phrase(table, key, lang, **values)
        assert "{" not in text


def test_a_missing_value_is_refused() -> None:
    with pytest.raises(KeyError):
        phrase("label_reason", "session_ended", "en", session_id="s1")


def test_a_language_outside_the_set_is_refused() -> None:
    with pytest.raises(ValueError, match="lang"):
        phrase("check_state", "passed", "de")


def test_an_unknown_table_or_key_is_refused() -> None:
    with pytest.raises(KeyError):
        keys("nope")
    with pytest.raises(KeyError):
        phrase("label", "nope", "en")


def test_the_english_reasons_keep_their_words() -> None:
    assert phrase("label_reason", "not_converged") == "solver did not converge"
    assert (
        phrase("label_reason", "promoted", session_id="s1", status="completed")
        == "promoted by session s1, completed"
    )
