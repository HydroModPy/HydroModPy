"""Contracts for simulation solver adapters.

The runner stays generic by delegating every solver-specific call to an
adapter. Each adapter knows how to execute one supported
``(process_type, solver_name)`` pair against the generic runtime contracts.

Family-specific helper functions live in sibling packages:

- ``adapters/flow/modflow_common.py``
- ``adapters/transport/common.py``
"""

from __future__ import annotations

from typing import Protocol

from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult


class SolverAdapter(Protocol):
    """Adapt one generic ``ProcessRun`` to one concrete solver implementation."""

    process_type: str
    solver_name: str

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Run the concrete solver for *ctx.run* and return its outputs."""
