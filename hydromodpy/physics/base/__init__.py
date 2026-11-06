"""
Base Package: Shared Process Building Blocks
============================================

This package exposes generic, process-agnostic components used by concrete
process modules (for example `flow`, `transport`):

- base runtime abstraction (`ProcessSpatial`),
- shared payload models (`InitialCondition`, `BoundaryCondition`, `SinkSource`),
- shared normalization helpers.

Import from this package when you need reusable primitives that should remain
independent from process-specific business rules.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "InitialCondition",
    "BoundaryCondition",
    "SinkSource",
    "ConstantForcing",
    "CsvForcing",
    "HeadForcing",
    "PiecewiseForcing",
    "SeasonalForcing",
    "SurfaceRateForcing",
    "TimeSeriesForcing",
    "VolumeRateForcing",
    "normalize_initial_condition_payload",
    "normalize_boundary_condition_payload",
    "normalize_sink_source_payload",
    "TInitialConditions",
    "ProcessSpatial",
]

_LAZY_IMPORTS = {
    "BoundaryCondition": "hydromodpy.physics.base.payloads:BoundaryCondition",
    "normalize_boundary_condition_payload": (
        "hydromodpy.physics.base.payloads:normalize_boundary_condition_payload"
    ),
    "ConstantForcing": "hydromodpy.physics.base.forcing:ConstantForcing",
    "CsvForcing": "hydromodpy.physics.base.forcing:CsvForcing",
    "HeadForcing": "hydromodpy.physics.base.forcing:HeadForcing",
    "PiecewiseForcing": "hydromodpy.physics.base.forcing:PiecewiseForcing",
    "SeasonalForcing": "hydromodpy.physics.base.forcing:SeasonalForcing",
    "SurfaceRateForcing": "hydromodpy.physics.base.forcing:SurfaceRateForcing",
    "TimeSeriesForcing": "hydromodpy.physics.base.forcing:TimeSeriesForcing",
    "VolumeRateForcing": "hydromodpy.physics.base.forcing:VolumeRateForcing",
    "InitialCondition": "hydromodpy.physics.base.payloads:InitialCondition",
    "normalize_initial_condition_payload": (
        "hydromodpy.physics.base.payloads:normalize_initial_condition_payload"
    ),
    "ProcessSpatial": "hydromodpy.physics.base.process_spatial:ProcessSpatial",
    "TInitialConditions": "hydromodpy.physics.base.process_spatial:TInitialConditions",
    "SinkSource": "hydromodpy.physics.base.payloads:SinkSource",
    "normalize_sink_source_payload": (
        "hydromodpy.physics.base.payloads:normalize_sink_source_payload"
    ),
}


def __getattr__(name: str):
    try:
        target = _LAZY_IMPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module_path, attr_name = target.split(":", 1)
    module = import_module(module_path)
    attr = getattr(module, attr_name)
    globals()[name] = attr
    return attr
