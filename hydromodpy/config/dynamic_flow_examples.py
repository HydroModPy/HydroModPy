"""Provider implementing core's DynamicFlowExamplesProvider Protocol.

Wired in by :mod:`hydromodpy._bootstrap` so the ``core/toml_io/generator.py``
module can render commented examples for the dynamic ``[flow.param.*]``,
``[flow.bc.*]`` and ``[flow.sinks_sources.*]`` blocks without importing
``physics`` or ``spatial`` directly.
"""

from __future__ import annotations

from collections.abc import Callable

from hydromodpy.physics.flow.boundary_conditions import FlowBoundaryConditionConfig
from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig
from hydromodpy.spatial.field.core.field_param_config import (
    FieldBaseSection,
    FieldHomogeneousSection,
)

_FLOW_PARAM_EXAMPLES: tuple[tuple[str, str, str], ...] = (
    ("K", "homogeneous", "m/s"),
    ("Sy", "homogeneous", "-"),
    ("Ss", "homogeneous", "m-1"),
)


class DynamicFlowExamples:
    """Render dynamic flow example blocks for the TOML generator."""

    def render(self, threshold: int, section_renderer: Callable) -> list[str]:
        out: list[str] = []
        out.append("")
        out.append("# " + "-" * 70)
        out.append("# Flow field parameters - one [flow.param.<id>.field] + one")
        out.append("# [flow.param.<id>.field_homogeneous] per id declared in")
        out.append("# [flow].param_list. Example block below for K, Sy, Ss.")
        out.append("# " + "-" * 70)
        for pid, kind, unit in _FLOW_PARAM_EXAMPLES:
            out.extend(
                section_renderer(
                    f"flow.param.{pid}.field",
                    FieldBaseSection,
                    threshold,
                    values={"id": pid, "kind": kind, "unit": unit},
                    _depth=0,
                )
            )
            out.extend(
                section_renderer(
                    f"flow.param.{pid}.field_homogeneous",
                    FieldHomogeneousSection,
                    threshold,
                    _depth=0,
                )
            )

        out.append("")
        out.append("# " + "-" * 70)
        out.append("# Flow boundary conditions - one block per id listed in")
        out.append("# [flow].active_bc. Supported keys: [flow.bc.dirichlet.<side>],")
        out.append("# [flow.bc.cauchy.drainage], [flow.bc.robin.drainage].")
        out.append("# Example: a top-domain Cauchy drainage BC.")
        out.append("# " + "-" * 70)
        out.extend(
            section_renderer(
                "flow.bc.cauchy.drainage",
                FlowBoundaryConditionConfig,
                threshold,
                values={"application_domain": "top", "type": "cauchy", "unit": "m2/s"},
                _depth=0,
            )
        )

        out.append("")
        out.append("# " + "-" * 70)
        out.append("# Flow diffuse recharge - emitted when 'recharge' is listed in")
        out.append("# [flow].active_sinks_sources. Values are taken from the data")
        out.append("# layer ([data.recharge]) unless overridden here.")
        out.append("# " + "-" * 70)
        out.extend(
            section_renderer(
                "flow.sinks_sources.recharge",
                FlowRechargeConfig,
                threshold,
                _depth=0,
            )
        )
        return out


__all__ = ["DynamicFlowExamples"]
