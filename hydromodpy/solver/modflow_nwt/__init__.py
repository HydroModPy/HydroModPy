"""MODFLOW-NWT solver package."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "FlowModflowInputs",
    "FlowToModflowAdapter",
    "ModflowNwt",
    "ModflowConfig",
    "ModflowSpecifParams",
    "ModflowPreprocessOptions",
    "ModflowRunOptions",
    "ModflowPostprocessOptions",
    "Modpath",
    "Mt3dms",
]

_LAZY_IMPORTS = {
    "FlowModflowInputs": "hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter:FlowModflowInputs",
    "FlowToModflowAdapter": "hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter:FlowToModflowAdapter",
    "ModflowNwt": "hydromodpy.solver.modflow_nwt.nwt.nwt_solver:ModflowNwt",
    "ModflowConfig": "hydromodpy.solver.modflow_nwt.nwt.nwt_config:ModflowConfig",
    "ModflowSpecifParams": "hydromodpy.solver.modflow_nwt.nwt.nwt_config:ModflowSpecifParams",
    "ModflowPreprocessOptions": "hydromodpy.solver.modflow_common.options:ModflowPreprocessOptions",
    "ModflowRunOptions": "hydromodpy.solver.modflow_common.options:ModflowRunOptions",
    "ModflowPostprocessOptions": "hydromodpy.solver.modflow_common.options:ModflowPostprocessOptions",
    "Modpath": "hydromodpy.solver.modflow_nwt.modpath.modpath:Modpath",
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
