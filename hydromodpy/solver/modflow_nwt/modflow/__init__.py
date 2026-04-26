"""MODFLOW-NWT flow solver components."""

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
]

_LAZY_IMPORTS = {
    "ModflowPostprocessOptions": "hydromodpy.solver.modflow_common.options:ModflowPostprocessOptions",
    "ModflowPreprocessOptions": "hydromodpy.solver.modflow_common.options:ModflowPreprocessOptions",
    "ModflowRunOptions": "hydromodpy.solver.modflow_common.options:ModflowRunOptions",
    "FlowModflowInputs": "hydromodpy.solver.modflow_nwt.modflow.flow_to_modflow_adapter:FlowModflowInputs",
    "FlowToModflowAdapter": "hydromodpy.solver.modflow_nwt.modflow.flow_to_modflow_adapter:FlowToModflowAdapter",
    "ModflowConfig": "hydromodpy.solver.modflow_nwt.modflow.nwt_config:ModflowConfig",
    "ModflowSpecifParams": "hydromodpy.solver.modflow_nwt.modflow.nwt_config:ModflowSpecifParams",
    "Modflow": "hydromodpy.solver.modflow_nwt.modflow.nwt_solver:Modflow",
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
