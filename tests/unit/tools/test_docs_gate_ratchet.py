"""The documentation gates of the parameter reference may go down, never up.

The gates count the user keys whose Pydantic field lacks what the reference
needs: a description, a unit, an explanation of each choice, a declared
condition. Their totals are pinned in tools/docs/field_gates_baseline.json.
A new field without a description or a unit raises a total and fails here.
"""

from __future__ import annotations

import json

import pytest

from tools.docs import field_registry


@pytest.fixture(scope="module")
def totals() -> dict[str, int]:
    _payload, gate_counts = field_registry.build_payload("test")
    return field_registry.gate_totals(gate_counts)


def test_no_gate_total_goes_up(totals: dict[str, int]) -> None:
    baseline = json.loads(field_registry.GATE_BASELINE.read_text())
    failures = field_registry.ratchet_failures(totals, baseline)
    assert not failures, (
        "A documentation gate of the parameter reference went up:\n  "
        + "\n  ".join(failures)
        + "\nFix the Field(...) of the new key: a description, a unit, value_docs or "
        "a VisibleWhen. The failing keys are listed by "
        "python -m tools.docs.field_registry OUT.json --gates GATES.json."
    )


def test_the_baseline_names_every_gate() -> None:
    baseline = json.loads(field_registry.GATE_BASELINE.read_text())
    assert set(baseline) == set(field_registry.GATE_TITLES)


def test_a_total_above_its_pin_is_reported() -> None:
    failures = field_registry.ratchet_failures(
        {"G2_no_description": 3, "G6_jargon": 0},
        {"G2_no_description": 2, "G6_jargon": 1},
    )
    assert len(failures) == 1
    assert failures[0].startswith("G2_no_description: 3 > 2")


def test_a_gate_missing_from_the_baseline_is_reported() -> None:
    failures = field_registry.ratchet_failures({"G6_jargon": 0}, {})
    assert failures == ["G6_jargon: 0, and the baseline has no entry for this gate"]
