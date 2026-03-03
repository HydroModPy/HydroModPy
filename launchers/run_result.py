"""Shared state object passed through all launcher phases and hooks."""

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
    from hydromodpy.data_managers.oceanic import Oceanic
    from hydromodpy.domain import Domain
    from hydromodpy.process import Flow, Transport
    from hydromodpy.solver.modflow_nwt import Modflow, Modpath, Mt3dms
    from hydromodpy.solver.modflow6 import Modflow6, Modflow6Transport


@dataclass
class RunResult:
    """Accumulates every object produced during the launcher pipeline."""

    cfg: HydroModPyConfig
    config_path: Path
    raw_toml: dict[str, Any]
    simulation_plan: Any = field(default=None)  # SimulationPlan
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

    # Flow phase
    model_modflow: Any = field(default=None)  # Modflow | Modflow6

    # Particles phase
    model_modpath: Any = field(default=None)  # Modpath

    # Transport phase
    model_transport: Any = field(default=None)  # Mt3dms | Modflow6Transport
