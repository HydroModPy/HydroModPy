"""Mutable runtime state threaded through workflow steps.

Three canonical scopes:

- ``setup``: structural objects prepared once (workspace, domain, flow, ...);
- ``loaded_data``: loaded support data (climatic, oceanic, hydrometry, ...);
- ``execution``: run outputs and registries (planned runs, produced models).

Plus result-store lifecycle fields (``store``, ``sim_id``,
``postprocess_runner``) used by the workflow layer.

Canonical access is explicit:

- ``state.setup.<...>`` for structural runtime context,
- ``state.loaded_data.<...>`` for loaded datasets,
- ``state.execution.<...>`` for run outputs and execution registries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.state.data import LoadedDataContext
from hydromodpy.core.state.execution import ExecutionRegistry
from hydromodpy.core.state.setup import SetupContext

if TYPE_CHECKING:
    from hydromodpy.data.plan import DataLoadPlan
    from hydromodpy.master_config.hydromodpy_config import HydroModPyConfig


@dataclass
class WorkflowContext:
    """Mutable workflow state split into setup/loaded_data/execution scopes.

    ``models_by_run_id`` is the source of truth for produced solver models.
    Concrete solver instances are resolved explicitly from that registry.

    Also carries result-store lifecycle fields needed by the workflow layer:
    ``store``, ``sim_id``, and ``postprocess_runner``.
    """

    cfg: HydroModPyConfig
    config_path: Path
    raw_toml: dict[str, Any]
    data_plan: DataLoadPlan | None = None
    setup: SetupContext = field(default_factory=SetupContext)
    loaded_data: LoadedDataContext = field(default_factory=LoadedDataContext)
    execution: ExecutionRegistry = field(default_factory=ExecutionRegistry)

    # Result-store lifecycle (formerly in WorkflowContext only).
    store: Any = field(default=None, repr=False)
    sim_id: str | None = None
    parent_sim_id: str | None = None
    postprocess_runner: Any = field(default=None, repr=False)

    def get_model(self, run_id: str) -> Any:
        """Return the exact model produced by a concrete process run."""
        return self.execution.models_by_run_id[run_id]

    def get_run_for_solver(self, solver_name: str) -> Any:
        """Return the unique planned run matching ``solver_name``, if any."""
        matches = [
            run for run in self.execution.process_runs_by_id.values() if run.solver == solver_name
        ]
        if len(matches) > 1:
            raise ValueError(
                f"Expected at most one run for solver '{solver_name}', got {len(matches)}."
            )
        return matches[0] if matches else None

    def get_model_for_solver(self, solver_name: str) -> Any:
        """Return the produced model for ``solver_name``, if that run completed."""
        run = self.get_run_for_solver(solver_name)
        if run is None:
            return None
        return self.execution.models_by_run_id.get(run.id)
