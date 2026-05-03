"""Public process namespace.

Canonical process objects live in concrete subpackages such as
``hydromodpy.physics.flow`` and ``hydromodpy.physics.transport``.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "BoundaryCondition",
    "Flow",
    "FlowConfig",
    "FlowRegime",
    "FlowRegimeInput",
    "FlowInitialCondition",
    "FlowInitialConditions",
    "InitialCondition",
    "ProcessSpatial",
    "ProcessSpatialConfig",
    "SinkSource",
    "Transport",
    "TransportConfig",
    "TransportInitialConditions",
    "is_permanent_flow_regime",
    "normalize_flow_regime",
]

_LAZY_IMPORTS = {
    "BoundaryCondition": "hydromodpy.physics.base:BoundaryCondition",
    "InitialCondition": "hydromodpy.physics.base:InitialCondition",
    "ProcessSpatial": "hydromodpy.physics.base:ProcessSpatial",
    "ProcessSpatialConfig": "hydromodpy.physics.base:ProcessSpatialConfig",
    "SinkSource": "hydromodpy.physics.base:SinkSource",
    "Flow": "hydromodpy.physics.flow:Flow",
    "FlowConfig": "hydromodpy.physics.flow:FlowConfig",
    "FlowRegime": "hydromodpy.physics.flow:FlowRegime",
    "FlowRegimeInput": "hydromodpy.physics.flow:FlowRegimeInput",
    "FlowInitialCondition": "hydromodpy.physics.flow:FlowInitialCondition",
    "FlowInitialConditions": "hydromodpy.physics.flow:FlowInitialConditions",
    "Transport": "hydromodpy.physics.transport:Transport",
    "TransportConfig": "hydromodpy.physics.transport:TransportConfig",
    "TransportInitialConditions": "hydromodpy.physics.transport:TransportInitialConditions",
    "is_permanent_flow_regime": "hydromodpy.physics.flow:is_permanent_flow_regime",
    "normalize_flow_regime": "hydromodpy.physics.flow:normalize_flow_regime",
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
