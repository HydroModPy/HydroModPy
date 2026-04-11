"""Analysis and reporting layer for HydroModPy.

The analysis package exposes display/postprocessing helpers, but those
dependencies are relatively heavy. Keep package import lightweight so core
calibration modules can be used without importing plotting/reporting stacks.
"""

from __future__ import annotations

import importlib
from typing import Any


_SUBMODULES = {
    "calibration": "hydromodpy.analysis.calibration",
    "display": "hydromodpy.analysis.display",
    "postprocess": "hydromodpy.analysis.postprocess",
}

_LAZY_EXPORTS = {
    "DisplayConfig": ("hydromodpy.analysis.display", "DisplayConfig"),
    "DisplayOptions": ("hydromodpy.analysis.display", "DisplayOptions"),
    "DisplaySectionOptions": (
        "hydromodpy.analysis.display",
        "DisplaySectionOptions",
    ),
    "display_options_from_raw_toml": (
        "hydromodpy.analysis.display",
        "display_options_from_raw_toml",
    ),
    "observed_discharge_series": (
        "hydromodpy.analysis.display",
        "observed_discharge_series",
    ),
    "observed_piezometry_series": (
        "hydromodpy.analysis.display",
        "observed_piezometry_series",
    ),
    "plot_boussinesq_flow_suite": (
        "hydromodpy.analysis.display",
        "plot_boussinesq_flow_suite",
    ),
    "plot_flow_suite": ("hydromodpy.analysis.display", "plot_flow_suite"),
    "plot_particles_suite": (
        "hydromodpy.analysis.display",
        "plot_particles_suite",
    ),
    "plot_transport_suite": (
        "hydromodpy.analysis.display",
        "plot_transport_suite",
    ),
    "PosthocContext": ("hydromodpy.analysis.display", "PosthocContext"),
    "plot_posthoc_all": ("hydromodpy.analysis.display", "plot_posthoc_all"),
    "plot_posthoc_flow_suite": (
        "hydromodpy.analysis.display",
        "plot_posthoc_flow_suite",
    ),
    "plot_posthoc_particles_suite": (
        "hydromodpy.analysis.display",
        "plot_posthoc_particles_suite",
    ),
    "PostprocessConfig": (
        "hydromodpy.analysis.postprocess",
        "PostprocessConfig",
    ),
    "FlowPostprocessConfig": (
        "hydromodpy.analysis.postprocess",
        "FlowPostprocessConfig",
    ),
    "FlowNetcdfPostprocessConfig": (
        "hydromodpy.analysis.postprocess",
        "FlowNetcdfPostprocessConfig",
    ),
    "FlowTimeseriesPostprocessConfig": (
        "hydromodpy.analysis.postprocess",
        "FlowTimeseriesPostprocessConfig",
    ),
    "IntermittencyPostprocessConfig": (
        "hydromodpy.analysis.postprocess",
        "IntermittencyPostprocessConfig",
    ),
    "TransportPostprocessConfig": (
        "hydromodpy.analysis.postprocess",
        "TransportPostprocessConfig",
    ),
    "TransportNetcdfPostprocessConfig": (
        "hydromodpy.analysis.postprocess",
        "TransportNetcdfPostprocessConfig",
    ),
    "TransportTimeseriesPostprocessConfig": (
        "hydromodpy.analysis.postprocess",
        "TransportTimeseriesPostprocessConfig",
    ),
}


def __getattr__(name: str) -> Any:
    """Load analysis submodules and legacy public symbols on first access."""
    if name in _SUBMODULES:
        module = importlib.import_module(_SUBMODULES[name])
        globals()[name] = module
        return module
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'hydromodpy.analysis' has no attribute {name!r}")


__all__ = [*_SUBMODULES, *_LAZY_EXPORTS]
