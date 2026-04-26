"""Planning layer for simulation orchestration."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "ProcessRun",
    "RunContext",
    "RunExecutionResult",
    "SimulationConfig",
    "SimulationPlan",
    "SimulationPlanner",
    "SimulationProcessConfig",
    "SimulationTimeConfig",
]

_LAZY_IMPORTS = {
    "SimulationConfig": "hydromodpy.simulation.planning.config:SimulationConfig",
    "SimulationProcessConfig": "hydromodpy.simulation.planning.config:SimulationProcessConfig",
    "SimulationTimeConfig": "hydromodpy.simulation.planning.config:SimulationTimeConfig",
    "ProcessRun": "hydromodpy.simulation.planning.plan:ProcessRun",
    "RunContext": "hydromodpy.simulation.planning.plan:RunContext",
    "RunExecutionResult": "hydromodpy.simulation.planning.plan:RunExecutionResult",
    "SimulationPlan": "hydromodpy.simulation.planning.plan:SimulationPlan",
    "SimulationPlanner": "hydromodpy.simulation.planning.planner:SimulationPlanner",
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
