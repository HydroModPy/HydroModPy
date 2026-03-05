"""Concrete runtime state shared across one launcher session.

``RunResult`` separates three concerns:

- ``setup``: structural objects prepared once (workspace, domain, flow, ...);
- ``data``: loaded support data (climatic, oceanic, hydrometry, ...);
- ``results``: execution outputs and registries (plans, produced models).

Callers are expected to use explicit scopes:

- ``result.setup.<...>`` for structural runtime context,
- ``result.data.<...>`` for loaded datasets,
- ``result.results.<...>`` for produced outputs and plan metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.data_managers.run_data_state import RunDataState
from hydromodpy.simulation.run_execution_state import RunExecutionState
from hydromodpy.watershed.run_setup_state import RunSetupState

if TYPE_CHECKING:
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig


@dataclass
class RunResult:
    """Mutable launcher state split into setup/data/results scopes.

    ``models_by_run_id`` is the source of truth for produced solver models.
    Concrete solver instances are resolved explicitly from that registry.
    """

    cfg: HydroModPyConfig
    config_path: Path
    raw_toml: dict[str, Any]
    setup: RunSetupState = field(default_factory=RunSetupState)
    data: RunDataState = field(default_factory=RunDataState)
    results: RunExecutionState = field(default_factory=RunExecutionState)

    def get_model(self, run_id: str) -> Any:
        """Return the exact model produced by a concrete process run."""

        return self.results.models_by_run_id[run_id]

    def get_run_for_solver(self, solver_name: str) -> Any:
        """Return the unique planned run matching ``solver_name``, if any.

        This is the practical explicit lookup helper used when several runs
        exist and caller code wants to target one concrete solver backend
        directly instead of relying on family-wide shortcuts.
        """

        matches = [
            run for run in self.results.process_runs_by_id.values() if run.solver == solver_name
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
        return self.results.models_by_run_id.get(run.id)
