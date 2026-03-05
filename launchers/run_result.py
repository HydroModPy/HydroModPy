"""Concrete runtime state shared across the launcher pipeline.

This module holds the mutable "working memory" of one launcher session.
It is useful to distinguish three layers:

- the config describes what the user asked for;
- the ``SimulationPlan`` describes which concrete runs must execute, in order;
- ``RunResult`` stores the real objects created while that plan is executed.

In practice, ``RunResult`` is the runtime state passed between setup, data,
hooks, and ``SimulationRunner``. As execution progresses, it accumulates both:

- shared prepared objects such as ``workspace``, ``domain``, ``flow``, and
  ``transport``;
- produced solver models, with ``models_by_run_id`` as the canonical registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.simulation.plan import ProcessRun, SimulationPlan
    from hydromodpy.watershed.workspace import Workspace
    from hydromodpy.watershed.settings import Settings
    from hydromodpy.watershed.climatic import Climatic
    from hydromodpy.watershed.hydrography import Hydrography
    from hydromodpy.watershed.intermittency import Intermittency
    from hydromodpy.data_managers.hydrometry.station_set import StationSet
    from hydromodpy.data_managers.piezometry.piezometer_set import PiezometerSet
    from hydromodpy.data_managers.oceanic import Oceanic
    from hydromodpy.domain import Domain
    from hydromodpy.process import Flow, Transport
    from hydromodpy.solver.modflow_nwt import Modflow, Modpath, Mt3dms
    from hydromodpy.solver.modflow6 import Modflow6, Modflow6Transport


@dataclass
class RunResult:
    """Accumulate the mutable objects produced during one launcher run.

    ``models_by_run_id`` is the source of truth for produced solver models.
    Concrete solver instances are resolved explicitly from that registry.
    """

    cfg: HydroModPyConfig
    config_path: Path
    raw_toml: dict[str, Any]
    simulation_plan: Any = field(default=None)  # SimulationPlan
    data_plan: Any = field(default=None)  # DataLoadPlan
    process_runs_by_id: dict[str, Any] = field(default_factory=dict)  # ProcessRun
    models_by_run_id: dict[str, Any] = field(default_factory=dict)

    # Setup phase
    workspace: Any = field(default=None)   # Workspace
    geographic: Any = field(default=None)  # Geographic
    domain: Any = field(default=None)      # Domain
    flow: Any = field(default=None)        # Flow
    transport: Any = field(default=None)   # Transport
    settings: Any = field(default=None)    # Settings

    # Data phase
    climatic: Any = field(default=None)       # Climatic
    oceanic: Any = field(default=None)        # Oceanic
    hydrography: Any = field(default=None)    # Hydrography
    intermittency: Any = field(default=None)  # Intermittency
    hydrometry: Any = field(default=None)     # StationSet
    piezometry: Any = field(default=None)     # PiezometerSet

    def get_model(self, run_id: str) -> Any:
        """Return the exact model produced by a concrete process run."""

        return self.models_by_run_id[run_id]

    def get_run_for_solver(self, solver_name: str) -> Any:
        """Return the unique planned run matching ``solver_name``, if any.

        This is the practical explicit lookup helper used when several runs
        exist and caller code wants to target one concrete solver backend
        directly instead of relying on family-wide shortcuts.
        """

        matches = [run for run in self.process_runs_by_id.values() if run.solver == solver_name]
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
        return self.models_by_run_id.get(run.id)
