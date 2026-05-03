"""Typed option containers shared by MODFLOW-family workflow stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ModflowPreprocessOptions:
    """Options consumed by ``ModflowNwt.pre_processing``."""

    box: bool = True
    sink_fill: bool = False
    check_grid: bool = True
    time_grid: Any = None


@dataclass(slots=True)
class ModflowRunOptions:
    """Options consumed by ``ModflowNwt.processing``."""

    write_model: bool = True
    run_model: bool = False
    link_mt3dms: bool = False
    verbose: bool = True


@dataclass(slots=True)
class ModflowPostprocessOptions:
    """Options consumed by ``ModflowNwt.post_processing``."""

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
    native_mesh_npz: bool = False
    native_mesh_csv: bool = False
    native_mesh_vtu: bool = False
    native_mesh_png: bool = False


__all__ = [
    "ModflowPreprocessOptions",
    "ModflowRunOptions",
    "ModflowPostprocessOptions",
]
