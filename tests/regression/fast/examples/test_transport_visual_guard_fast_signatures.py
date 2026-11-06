"""Golden-signature regression for the transport MF6 GWT DISV visual-guard example.

The example ``run_visual_guard.py`` produces a fixed numeric signature for each
synthetic fast case (mesh, flow, transport numbers, plume moments, ...). This
test pins those signatures to a committed golden JSON so that any drift in the
synthetic model is caught. It does not run MODFLOW 6; the synthetic mode is a
closed-form generator, so the comparison is deterministic and fast.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests._helpers.transport_guard import fast_cases, load_guard_module

REFERENCE_PATH = (
    Path(__file__).resolve().parent / "golden" / "transport_visual_guard_fast_signatures.json"
)


def _signature_subset(result: Any) -> dict[str, Any]:
    return {
        "mesh": result.signatures["mesh"],
        "flow": result.signatures["flow"],
        "transport_numbers": result.signatures["transport_numbers"],
        "analytical_comparison": result.signatures["analytical_comparison"],
        "final": result.signatures["time_signatures"][-1],
    }


@pytest.mark.regression
@pytest.mark.fast
def test_fast_synthetic_signatures_match_committed_reference() -> None:
    guard = load_guard_module()
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))

    actual = {}
    for case in fast_cases(guard):
        result = guard.run_synthetic_case(case)
        actual[case.name] = _signature_subset(result)

    assert actual == reference["cases"]
