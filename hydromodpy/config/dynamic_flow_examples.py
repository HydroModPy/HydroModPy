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
from hydromodpy.spatial.field.field_param_config import FieldHomogeneousSection

_FLOW_PARAM_EXAMPLES: tuple[tuple[str, str, str], ...] = (
    ("K", "homogeneous", "m/s"),
    ("Sy", "homogeneous", "-"),
    ("Ss", "homogeneous", "1/m"),
)


class DynamicFlowExamples:
    """Render dynamic flow example blocks for the TOML generator."""

    def render(self, threshold: int, section_renderer: Callable[..., list[str]]) -> list[str]:
        out: list[str] = []
        out.append("")
        out.append("# " + "-" * 70)
        out.append("# Flow field parameters - one [flow.param.<id>.field] per id declared in")
        out.append("# [flow].param_list. Example block below for K, Sy, Ss.")
        out.append("# " + "-" * 70)
        for pid, kind, unit in _FLOW_PARAM_EXAMPLES:
            out.extend(
                section_renderer(
                    f"flow.param.{pid}.field",
                    FieldHomogeneousSection,
                    threshold,
                    values={"id": pid, "kind": kind, "unit": unit},
                    _depth=0,
                )
            )

        out.append("")
        out.append("# " + "-" * 70)
        out.append("# Flow boundary conditions. A boundary is keyed by WHAT IT IS,")
        out.append("# [flow.bc.<id>], with the canonical ids and their kind, domain")
        out.append("# and units held by the flow boundary-condition registry.")
        out.append("# Declaring a block is what activates the boundary. A boundary the")
        out.append("# registry describes entirely takes an empty block. Write keys")
        out.append("# only to depart from that default, for instance to impose a")
        out.append("# conductance. enabled = false keeps the block and switches it off.")
        out.append("# " + "-" * 70)
        out.extend(
            section_renderer(
                "flow.bc.drainage",
                FlowBoundaryConditionConfig,
                threshold,
                values={"unit": "m2/s"},
                _depth=0,
            )
        )

        out.append("")
        out.append("# " + "-" * 70)
        out.append("# Flow diffuse recharge - declaring the table activates it. A series")
        out.append("# loaded from [data.recharge]")
        out.append("# or computed by the soil section replaces values.")
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
