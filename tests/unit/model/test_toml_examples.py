"""The commented examples of the dynamic [flow.*] blocks of the TOML template."""

from __future__ import annotations

from hydromodpy.core.config_kit.field_param.sections import FieldHomogeneousSection
from hydromodpy.model.boundaries.boundary_conditions import FlowBoundaryConditionConfig
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.model.toml_examples import DynamicFlowExamples


def test_the_examples_render_one_block_per_parameter_then_the_drain_and_the_recharge() -> None:
    calls: list[tuple[str, type, int, dict | None]] = []

    def renderer(
        section: str, model: type, threshold: int, values: dict | None = None
    ) -> list[str]:
        calls.append((section, model, threshold, values))
        return [f"[{section}]"]

    lines = DynamicFlowExamples().render(3, renderer)

    assert [call[0] for call in calls] == [
        "flow.param.K.field",
        "flow.param.Sy.field",
        "flow.param.Ss.field",
        "flow.bc.drainage",
        "flow.sinks_sources.recharge",
    ]
    assert [call[1] for call in calls] == [FieldHomogeneousSection] * 3 + [
        FlowBoundaryConditionConfig,
        FlowRechargeConfig,
    ]
    assert all(call[2] == 3 for call in calls)
    assert calls[0][3] == {"id": "K", "kind": "homogeneous", "unit": "m/s"}
    assert calls[3][3] == {"unit": "m2/s"}
    assert "[flow.bc.drainage]" in lines
    assert any(line.startswith("# Flow boundary conditions") for line in lines)
