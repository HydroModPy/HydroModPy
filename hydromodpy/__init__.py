"""Public entry points for HydroModPy."""

from __future__ import annotations

import importlib

from hydromodpy._lazy import LAZY_IMPORTS as _LAZY_IMPORTS
from hydromodpy._lazy import MODULE_EXPORTS as _MODULE_EXPORTS
from hydromodpy.core.version import __version__

__author__ = "Alexandre Gauvain, Ronan Abherve, Jean-Raynald de Dreuzy"
__email__ = (
    "alexandre.gauvain.ag@gmail.com, ronan.abherve@gmail.com, jean-raynald.de-dreuzy@univ-rennes.fr"
)

_DIRECT_EXPORTS = ["__version__"]


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
