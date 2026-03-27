"""Unit tests for inline-unit parsing in flow.param payloads."""

from __future__ import annotations

import pytest

from hydromodpy.process.flow.flow import Flow
from hydromodpy.process.flow.flow_config import FlowConfig


def test_flow_param_accepts_inline_units_with_mixed_families() -> None:
    cfg = FlowConfig(
        param_list=["K", "Ss", "Sy"],
        param={
            "K": {"id": "K", "kind": "homogeneous", "value": "8.64 m/day"},
            "Ss": {"id": "Ss", "kind": "homogeneous", "value": "1e-6 cm-1"},
            "Sy": {"id": "Sy", "kind": "homogeneous", "value": "0.2 -"},
        },
    )

    flow = Flow(cfg)
    assert float(flow.parameters["K"].value) == pytest.approx(1.0e-4)
    assert float(flow.parameters["Ss"].value) == pytest.approx(1.0e-4)
    assert float(flow.parameters["Sy"].value) == pytest.approx(0.2)


def test_flow_param_rejects_inline_unit_conflicting_with_field_unit() -> None:
    with pytest.raises(ValueError, match="mixes conflicting units"):
        cfg = FlowConfig(
            param_list=["K"],
            param={
                "K": {
                    "id": "K",
                    "kind": "homogeneous",
                    "unit": "m/day",
                    "value": "1.0 m/s",
                }
            },
        )
        _ = Flow(cfg)
