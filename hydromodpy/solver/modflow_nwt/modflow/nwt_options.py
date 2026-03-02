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
- Normalize ambiguous user inputs early (for example ``cross_ylim``
  type/shape) so downstream code can stay simple.
- Keep these containers lightweight: they are runtime switches, not a full
  domain/config schema.
- Recharge is NOT configured here; it belongs to ``flow.sinks_sources.recharge``
  (``FlowRechargeConfig``).
"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real


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
    plot_cross:
        Enable cross-section plotting in preprocessing diagnostics.
    cross_ylim:
        Optional Y-limits for cross-section plots as ``(ymin, ymax)``.
    """

    box: bool = True
    sink_fill: bool = False
    check_grid: bool = True
    plot_cross: bool = True
    cross_ylim: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        # Accept "empty" values as no explicit y-limits.
        if self.cross_ylim is None or self.cross_ylim == () or self.cross_ylim == []:
            self.cross_ylim = None
            return

        # Enforce one strict 2-item numeric tuple expected by plotting code.
        if not isinstance(self.cross_ylim, (tuple, list)) or len(self.cross_ylim) != 2:
            raise ValueError("cross_ylim must be None or a 2-item sequence (ymin, ymax).")

        ymin, ymax = self.cross_ylim
        if (
            isinstance(ymin, bool)
            or isinstance(ymax, bool)
            or not isinstance(ymin, Real)
            or not isinstance(ymax, Real)
        ):
            raise TypeError("cross_ylim values must be numeric.")
        self.cross_ylim = (float(ymin), float(ymax))


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
    groundwater_flux: bool = True
    groundwater_storage: bool = True
    accumulation_flux: bool = True
    persistency_index: bool = False
    intermittency_yearly: bool = False
    intermittency_monthly: bool = False
    intermittency_weekly: bool = False
    intermittency_daily: bool = False
    export_all_tif: bool = False
