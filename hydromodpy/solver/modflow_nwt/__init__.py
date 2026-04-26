"""MODFLOW-NWT solver package."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "FlowModflowInputs",
    "FlowToModflowAdapter",
    "Modflow",
    "ModflowConfig",
    "ModflowSpecifParams",
    "ModflowPreprocessOptions",
    "ModflowRunOptions",
    "ModflowPostprocessOptions",
    "Modpath",
    "Mt3dms",
]

_LAZY_IMPORTS = {
    "FlowModflowInputs": "hydromodpy.solver.modflow_nwt.modflow:FlowModflowInputs",
    "FlowToModflowAdapter": "hydromodpy.solver.modflow_nwt.modflow:FlowToModflowAdapter",
    "Modflow": "hydromodpy.solver.modflow_nwt.modflow:Modflow",
    "ModflowConfig": "hydromodpy.solver.modflow_nwt.modflow:ModflowConfig",
    "ModflowSpecifParams": "hydromodpy.solver.modflow_nwt.modflow:ModflowSpecifParams",
    "ModflowPreprocessOptions": "hydromodpy.solver.modflow_nwt.modflow:ModflowPreprocessOptions",
    "ModflowRunOptions": "hydromodpy.solver.modflow_nwt.modflow:ModflowRunOptions",
    "ModflowPostprocessOptions": "hydromodpy.solver.modflow_nwt.modflow:ModflowPostprocessOptions",
    "Modpath": "hydromodpy.solver.modflow_nwt.modpath:Modpath",
    "Mt3dms": "hydromodpy.solver.modflow_nwt.mt3dms:Mt3dms",
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
