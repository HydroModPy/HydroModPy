"""Public entry points for HydroModPy."""

from __future__ import annotations

import importlib

from hydromodpy._api import (
    batch,
    calibrate,
    catalog,
    compare,
    compare_pair,
    doctor,
    mesh,
    open,
    overview,
    report,
    run,
    testbed,
)
from hydromodpy._bootstrap import bootstrap
from hydromodpy._lazy import LAZY_IMPORTS as _LAZY_IMPORTS
from hydromodpy._lazy import MODULE_EXPORTS as _MODULE_EXPORTS
from hydromodpy.core.io.proj_bootstrap import bootstrap_proj
from hydromodpy.core.logging import LogManager
from hydromodpy.core.version import __version__

__author__ = "Alexandre Gauvain, Ronan Abherve, Jean-Raynald de Dreuzy"
__email__ = (
    "alexandre.gauvain.ag@gmail.com, ronan.abherve@gmail.com, jean-raynald.de-dreuzy@univ-rennes.fr"
)

_log_manager = LogManager(mode="verbose", log_dir=None, overwrite=False)
# Public access to log manager for users
log_manager = _log_manager

_DIRECT_EXPORTS = [
    "open",
    "run",
    "calibrate",
    "catalog",
    "overview",
    "batch",
    "compare",
    "compare_pair",
    "mesh",
    "testbed",
    "report",
    "bootstrap_proj",
    "doctor",
    "log_manager",
    "__version__",
]


def __getattr__(name: str):
    if name in _MODULE_EXPORTS:
        module = importlib.import_module(_MODULE_EXPORTS[name])
        globals()[name] = module
        return module
    if name in _LAZY_IMPORTS:
        target = _LAZY_IMPORTS[name]
        if ":" in target:
            module_path, attr_name = target.split(":", 1)
        else:
            module_path, attr_name = target, name
        module = importlib.import_module(module_path)
        attr = getattr(module, attr_name)
        globals()[name] = attr
        return attr
    raise AttributeError(f"module 'hydromodpy' has no attribute {name!r}")


__all__ = [*_DIRECT_EXPORTS, *_LAZY_IMPORTS, *_MODULE_EXPORTS]

bootstrap()
