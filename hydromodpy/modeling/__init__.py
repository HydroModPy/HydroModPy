"""Compatibility facade for historical ``hydromodpy.modeling`` imports."""

from __future__ import annotations

import importlib

_MODULE_EXPORTS = {
    "modflow": "hydromodpy.solver.modflow_nwt.modflow",
    "modpath": "hydromodpy.solver.modflow_nwt.modpath",
    "masstransfer": "hydromodpy.solver.modflow_common.masstransfer",
    "timeseries": "hydromodpy.analysis.postprocess.timeseries",
    "netcdf": "hydromodpy.analysis.postprocess.netcdf",
}

_LAZY_IMPORTS = {
    "Modflow": "hydromodpy.solver.modflow_nwt.modflow",
    "Modpath": "hydromodpy.solver.modflow_nwt.modpath",
    "Masstransfer": "hydromodpy.solver.modflow_common.masstransfer",
    "Timeseries": "hydromodpy.analysis.postprocess.timeseries",
    "Netcdf": "hydromodpy.analysis.postprocess.netcdf",
}


def __getattr__(name: str):
    if name in _MODULE_EXPORTS:
        module = importlib.import_module(_MODULE_EXPORTS[name])
        globals()[name] = module
        return module
    if name in _LAZY_IMPORTS:
        module = importlib.import_module(_LAZY_IMPORTS[name])
        attr = getattr(module, name)
        globals()[name] = attr
        return attr
    raise AttributeError(f"module 'hydromodpy.modeling' has no attribute {name!r}")


__all__ = [
    "modflow",
    "modpath",
    "masstransfer",
    "timeseries",
    "netcdf",
    "Modflow",
    "Modpath",
    "Masstransfer",
    "Timeseries",
    "Netcdf",
]
