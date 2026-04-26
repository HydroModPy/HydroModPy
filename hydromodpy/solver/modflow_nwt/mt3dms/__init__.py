"""MT3DMS components for MODFLOW-NWT workflows."""

from __future__ import annotations

from importlib import import_module

__all__ = ["Mt3dms"]

_LAZY_IMPORTS = {
    "Mt3dms": "hydromodpy.solver.modflow_nwt.mt3dms.mt3dms:Mt3dms",
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
