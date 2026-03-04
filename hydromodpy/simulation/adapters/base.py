"""Contracts and shared helpers for simulation solver adapters.

The runner stays generic by delegating every solver-specific call to an
adapter. Each adapter knows how to execute one supported
``(process_type, solver_name)`` pair against the generic runtime contracts.
"""

from __future__ import annotations

from typing import Protocol

from hydromodpy.simulation.plan import ProcessRun, SimulationPlan
from hydromodpy.simulation.runtime import RunContext, RunExecutionResult


class SolverAdapter(Protocol):
    """Adapt one generic ``ProcessRun`` to one concrete solver implementation."""

    process_type: str
    solver_name: str

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Run the concrete solver for *ctx.run* and return its outputs."""


def has_single_process_run(plan: SimulationPlan, process_type: str) -> bool:
    """Return ``True`` when *plan* contains exactly one run of *process_type*."""

    return sum(1 for run in plan.runs if run.process_type == process_type) == 1


def run_label(plan: SimulationPlan, run: ProcessRun) -> str:
    """Return a short stable label for *run* inside its process family."""

    same_type_runs = [planned for planned in plan.runs if planned.process_type == run.process_type]
    for index, planned in enumerate(same_type_runs, start=1):
        if planned.id == run.id:
            prefix = {
                "flow": "f",
                "transport": "t",
            }.get(run.process_type, "r")
            return f"{prefix}{index}"

    raise ValueError(f"Process run '{run.id}' is not present in the provided simulation plan.")


def flow_model_name(plan: SimulationPlan, base_name: str, run: ProcessRun) -> str:
    """Return the stable model name used for one flow run."""

    if has_single_process_run(plan, "flow"):
        return base_name
    return f"{base_name}_{run_label(plan, run)}"


def transport_output_suffix(plan: SimulationPlan, run: ProcessRun) -> str:
    """Return the stable suffix used by one concentration transport run."""

    if run.process_type != "transport" or run.solver not in {"mt3dms", "modflow6gwt"}:
        raise ValueError(
            f"Transport run '{run.id}' is not a supported concentration transport run."
        )

    concentration_runs = [
        planned
        for planned in plan.runs
        if planned.process_type == "transport" and planned.solver in {"mt3dms", "modflow6gwt"}
    ]
    for index, planned in enumerate(concentration_runs, start=1):
        if planned.id == run.id:
            return f"_mt_s{index}"

    raise ValueError(
        f"Transport run '{run.id}' is not part of the concentration transport sequence."
    )
