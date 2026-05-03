from __future__ import annotations

import pytest

from hydromodpy.physics.flow.initial_conditions_config import normalize_flow_initial_conditions


def test_normalize_flow_initial_conditions_accepts_top_offset() -> None:
    result = normalize_flow_initial_conditions({"type": "top_offset", "value": "5 m"})

    assert result is not None
    assert result.h.type == "top_offset"
    assert result.h.value == pytest.approx(5.0)
    assert result.h.units == "m"


def test_normalize_flow_initial_conditions_rejects_negative_top_offset() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        normalize_flow_initial_conditions({"type": "top_offset", "value": "-1 m"})
