"""Concrete runtime state shared across one launcher session.

``LauncherRunState`` separates three concerns:

- ``setup``: structural objects prepared once (workspace, domain, flow, ...);
- ``loaded_data``: loaded support data (climatic, oceanic, hydrometry, ...);
- ``execution``: run outputs and registries (planned runs, produced models).

Canonical access is explicit:

- ``state.setup.<...>`` for structural runtime context,
- ``state.loaded_data.<...>`` for loaded datasets,
- ``state.execution.<...>`` for run outputs and execution registries.

Compatibility aliases are still provided:

- ``state.data`` mirrors ``state.loaded_data``,
- ``state.results`` mirrors ``state.execution``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.simulation.state.data import LoadedDataContext
from hydromodpy.simulation.state.execution import ExecutionRegistry
from hydromodpy.simulation.state.setup import SetupContext

if TYPE_CHECKING:
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.data_managers.plan import DataLoadPlan


@dataclass
class LauncherRunState:
    """Mutable launcher state split into setup/loaded_data/execution scopes.

    ``models_by_run_id`` is the source of truth for produced solver models.
    Concrete solver instances are resolved explicitly from that registry.
    """

    cfg: HydroModPyConfig
    config_path: Path
    raw_toml: dict[str, Any]
    data_plan: DataLoadPlan | None = None
    setup: SetupContext = field(default_factory=SetupContext)
    loaded_data: LoadedDataContext = field(default_factory=LoadedDataContext)
    execution: ExecutionRegistry = field(default_factory=ExecutionRegistry)

    @property
    def data(self) -> LoadedDataContext:
        """Backward-compatible alias for ``loaded_data``."""

        return self.loaded_data

    @data.setter
    def data(self, value: LoadedDataContext) -> None:
        self.loaded_data = value

    @property
    def results(self) -> ExecutionRegistry:
        """Backward-compatible alias for ``execution``."""

        return self.execution

    @results.setter
    def results(self, value: ExecutionRegistry) -> None:
        self.execution = value

    def get_model(self, run_id: str) -> Any:
        """Return the exact model produced by a concrete process run."""

        return self.execution.models_by_run_id[run_id]

    def get_run_for_solver(self, solver_name: str) -> Any:
        """Return the unique planned run matching ``solver_name``, if any.

        This is the practical explicit lookup helper used when several runs
        exist and caller code wants to target one concrete solver backend
        directly instead of relying on family-wide shortcuts.
        """

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


# Backward-compatible aliases kept while downstream imports migrate.
RunState = LauncherRunState
RunResult = LauncherRunState
