"""Runtime execution scope shared by launcher process runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hydromodpy.simulation.plan import ProcessRun, SimulationPlan


@dataclass
class ExecutionRegistry:
    """Execution-oriented metadata and produced model registry."""

    simulation_plan: SimulationPlan | None = None
    process_runs_by_id: dict[str, ProcessRun] = field(default_factory=dict)
    models_by_run_id: dict[str, Any] = field(default_factory=dict)
