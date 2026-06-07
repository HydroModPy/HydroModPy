"""MODPATH components for MODFLOW-NWT workflows."""

from __future__ import annotations

from importlib import import_module

__all__ = ["Modpath"]

_LAZY_IMPORTS = {
    "Modpath": "hydromodpy.solver.modflow_nwt.modpath.modpath:Modpath",
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
