"""Typed option containers for the MODFLOW-NWT workflow stages."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import Any


@dataclass(slots=True)
class ModflowPreprocessOptions:
    """Options consumed by ``Modflow.pre_processing``."""

    box: bool = True
    sink_fill: bool = False
    recharge: Any = 0.001
    first_clim: str | float = "mean"
    check_grid: bool = True
    plot_cross: bool = True
    cross_ylim: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.first_clim, str):
            first_clim_value = self.first_clim.strip().lower()
            if first_clim_value not in {"mean", "first"}:
                raise ValueError("first_clim must be 'mean', 'first', or a numeric value.")
            self.first_clim = first_clim_value

        if self.cross_ylim is None or self.cross_ylim == () or self.cross_ylim == []:
            self.cross_ylim = None
            return

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
    """Options consumed by ``Modflow.processing``."""

    write_model: bool = True
    run_model: bool = False
    link_mt3dms: bool = False
    verbose: bool = True


@dataclass(slots=True)
class ModflowPostprocessOptions:
    """Options consumed by ``Modflow.post_processing``."""

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
