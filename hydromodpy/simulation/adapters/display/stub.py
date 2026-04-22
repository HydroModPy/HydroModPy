"""Placeholder display adapters.

These stubs define the adapter interface for display/visualization phases.
Concrete implementations will wrap the existing ``display/`` module
into the simulation pipeline.
"""

from __future__ import annotations

from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult


class FlowDisplayAdapter:
    """Adapter for ``display/flow`` runs (stub)."""

    process_type = "display"
    solver_name = "flow"

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        raise NotImplementedError(
            "FlowDisplayAdapter is a stub. Implement by wrapping the flow display module."
        )


class TransportDisplayAdapter:
    """Adapter for ``display/transport`` runs (stub)."""

    process_type = "display"
    solver_name = "transport"

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        raise NotImplementedError(
            "TransportDisplayAdapter is a stub. Implement by wrapping the transport display module."
        )
