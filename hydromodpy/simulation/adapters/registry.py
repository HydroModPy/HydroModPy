"""Registry mapping simulation runs to solver adapters."""

from __future__ import annotations

from hydromodpy.simulation.adapters.base import SolverRunner
from hydromodpy.simulation.adapters.flow import (
    BoussinesqFlowAdapter,
    Modflow6FlowAdapter,
    ModflowNwtFlowAdapter,
)
from hydromodpy.simulation.adapters.transport import (
    Modflow6GwtTransportAdapter,
    ModpathTransportAdapter,
    Mt3dmsTransportAdapter,
)

_ADAPTERS: dict[tuple[str, str], SolverRunner] = {
    ("flow", "modflownwt"): ModflowNwtFlowAdapter(),
    ("flow", "modflow6"): Modflow6FlowAdapter(),
    ("flow", "boussinesq"): BoussinesqFlowAdapter(),
    ("transport", "modpath"): ModpathTransportAdapter(),
    ("transport", "mt3dms"): Mt3dmsTransportAdapter(),
    ("transport", "modflow6gwt"): Modflow6GwtTransportAdapter(),
}


def register_adapter(process_type: str, solver_name: str, adapter: SolverRunner) -> None:
    """Register a solver adapter for dynamic extension.

    External modules can call this to add adapters for new process types
    (e.g. postprocess, display) without modifying this file.
    """
    key = (process_type, solver_name)
    if key in _ADAPTERS:
        raise ValueError(
            f"Adapter already registered for {process_type}/{solver_name}."
        )
    _ADAPTERS[key] = adapter


def get_solver_adapter(process_type: str, solver_name: str) -> SolverRunner:
    """Return the adapter registered for one ``(process_type, solver_name)`` pair."""

    key = (process_type, solver_name)
    if key not in _ADAPTERS:
        raise ValueError(
            f"Unsupported simulation process/solver pair: {process_type}/{solver_name}."
        )
    return _ADAPTERS[key]
