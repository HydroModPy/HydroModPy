"""Typed option containers for MODFLOW-NWT workflow stages.

Why this module exists
----------------------
The solver pipeline is split into three explicit stages:
1) ``pre_processing``: prepare geometry/inputs and build FLOPY packages,
2) ``processing``: write and run the model,
3) ``post_processing``: compute and export diagnostic outputs.

Each stage accepts one typed options object from this module. This keeps calls
explicit and prevents long lists of loosely-typed keyword arguments.

Design philosophy
-----------------
- Keep defaults aligned with common HydroModPy workflows.
- Keep these containers lightweight: they are runtime switches, not a full
  domain/config schema.
- Recharge is NOT configured here; it belongs to ``flow.sinks_sources.recharge``
  (``FlowRechargeConfig``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ModflowPreprocessOptions:
    """Options consumed by ``Modflow.pre_processing``.

    Practical role
    --------------
    Control how raw geographic/process inputs are prepared before numerical
    simulation starts. Recharge configuration is handled at the process level
    via ``flow.sinks_sources.recharge`` (``FlowRechargeConfig``).

    Main knobs
    ----------
    box:
        If True, use buffered-box DEM support. If False, use watershed DEM.
    sink_fill:
        Enable/disable depression filling used before flow setup.
    check_grid:
        Enable internal grid consistency checks.
    time_grid:
        Canonical simulation-time grid injected by launcher runtime.
        Launcher flow runs require this grid; solver ``tgrid`` sections are no
        longer used as a fallback source for stress-period construction.
    """

    box: bool = True
    sink_fill: bool = False
    check_grid: bool = True
    time_grid: Any = None


@dataclass(slots=True)
class ModflowRunOptions:
    """Options consumed by ``Modflow.processing``.

    These flags control execution behavior only (not model physics):
    - writing input files,
    - launching the MODFLOW executable,
    - linking transport setup,
    - verbosity of runtime logs.
    """

    write_model: bool = True
    run_model: bool = False
    link_mt3dms: bool = False
    verbose: bool = True


@dataclass(slots=True)
class ModflowPostprocessOptions:
    """Options consumed by ``Modflow.post_processing``.

    Each boolean enables one output family (maps/indicators/time diagnostics).
    Turning a flag off skips the associated computation/export, which is useful
    to reduce runtime when only a subset of products is needed.
    """

    watertable_elevation: bool = True
    watertable_depth: bool = True
    seepage_areas: bool = True
    outflow_drain: bool = True
    outlet_discharge_east_side_m3_s: bool = False
    groundwater_flux: bool = True
    groundwater_storage: bool = True
    accumulation_flux: bool = True
    persistency_index: bool = False
    intermittency_yearly: bool = False
    intermittency_monthly: bool = False
    intermittency_weekly: bool = False
    intermittency_daily: bool = False
    export_all_tif: bool = False
