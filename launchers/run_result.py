"""Shared state object passed through all launcher phases and hooks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.watershed.workspace import Workspace
    from hydromodpy.watershed.settings import Settings
    from hydromodpy.watershed.climatic import Climatic
    from hydromodpy.watershed.hydrography import Hydrography
    from hydromodpy.watershed.intermittency import Intermittency
    from hydromodpy.data_managers.contracts.timeseries import PointRecord
    from hydromodpy.data_managers.oceanic import Oceanic
    from hydromodpy.domain import Domain
    from hydromodpy.process import Flow, Transport
    from hydromodpy.solver.modflow_nwt import Modflow, Modpath, Mt3dms
    from hydromodpy.solver.modflow6 import Modflow6, Modflow6Transport


@dataclass
class RunResult:
    """Accumulates every object produced during the launcher pipeline.

    Populated progressively by phase functions and hooks.  Each phase reads
    what was created before it and writes its own outputs back onto this object.
    """

    cfg: HydroModPyConfig
    config_path: Path
    raw_toml: dict[str, Any]          # raw tomllib dict – available to hooks

    # ── Phase: setup ─────────────────────────────────────────────────────────
    workspace:  Any = field(default=None)   # Workspace
    geographic: Any = field(default=None)   # Geographic
    domain:     Any = field(default=None)   # Domain
    flow:       Any = field(default=None)   # Flow
    transport:  Any = field(default=None)   # Transport
    settings:   Any = field(default=None)   # Settings

    # ── Phase: data ──────────────────────────────────────────────────────────
    climatic:    Any = field(default=None)  # Climatic
    oceanic:     Any = field(default=None)  # Oceanic
    # Below are None unless a hook populates them (example-specific data)
    hydrography: Any = field(default=None)  # Hydrography
    intermittency: Any = field(default=None)  # Intermittency
    hydrometry:  Any = field(default=None)  # list[PointRecord]

    # ── Phase: flow ──────────────────────────────────────────────────────────
    model_modflow: Any = field(default=None)   # Modflow | Modflow6

    # ── Phase: particles ────────────────────────────────────────────────────
    model_modpath: Any = field(default=None)   # Modpath

    # ── Phase: transport ────────────────────────────────────────────────────
    model_transport: Any = field(default=None)  # Mt3dms | Modflow6Transport
