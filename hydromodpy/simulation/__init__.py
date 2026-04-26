"""Simulation orchestration models and planning helpers."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "ExecutionRegistry",
    "WorkflowContext",
    "LoadedDataContext",
    "ProcessRun",
    "RunContext",
    "RunExecutionResult",
    "SetupContext",
    "ResolvedSimulationTimeWindow",
    "SimulationConfig",
    "SimulationPlan",
    "SimulationPlanner",
    "SimulationProcessConfig",
    "SimulationTimeConfig",
    "Workspace",
    "WorkspaceConfig",
    "ensure_flow",
    "ensure_process_context",
    "ensure_transport",
]

_LAZY_IMPORTS = {
    "ExecutionRegistry": "hydromodpy.core.state:ExecutionRegistry",
    "LoadedDataContext": "hydromodpy.core.state:LoadedDataContext",
    "SetupContext": "hydromodpy.core.state:SetupContext",
    "WorkflowContext": "hydromodpy.core.state:WorkflowContext",
    "ResolvedSimulationTimeWindow": "hydromodpy.core.time:ResolvedSimulationTimeWindow",
    "Workspace": "hydromodpy.core.workspace:Workspace",
    "WorkspaceConfig": "hydromodpy.core.workspace:WorkspaceConfig",
    "ensure_flow": "hydromodpy.simulation.execution:ensure_flow",
    "ensure_process_context": "hydromodpy.simulation.execution:ensure_process_context",
    "ensure_transport": "hydromodpy.simulation.execution:ensure_transport",
    "ProcessRun": "hydromodpy.simulation.planning:ProcessRun",
    "RunContext": "hydromodpy.simulation.planning:RunContext",
    "RunExecutionResult": "hydromodpy.simulation.planning:RunExecutionResult",
    "SimulationConfig": "hydromodpy.simulation.planning:SimulationConfig",
    "SimulationPlan": "hydromodpy.simulation.planning:SimulationPlan",
    "SimulationPlanner": "hydromodpy.simulation.planning:SimulationPlanner",
    "SimulationProcessConfig": "hydromodpy.simulation.planning:SimulationProcessConfig",
    "SimulationTimeConfig": "hydromodpy.simulation.planning:SimulationTimeConfig",
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
