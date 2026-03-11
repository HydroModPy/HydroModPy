"""Registry mapping simulation runs to solver adapters."""

from __future__ import annotations

from hydromodpy.simulation.adapters.base import SolverAdapter
from hydromodpy.simulation.adapters.flow import Modflow6FlowAdapter, ModflowNwtFlowAdapter
from hydromodpy.simulation.adapters.transport import (
    Modflow6GwtTransportAdapter,
    ModpathTransportAdapter,
    Mt3dmsTransportAdapter,
)

_ADAPTERS: dict[tuple[str, str], SolverAdapter] = {
    ("flow", "modflownwt"): ModflowNwtFlowAdapter(),
    ("flow", "modflow6"): Modflow6FlowAdapter(),
    ("transport", "modpath"): ModpathTransportAdapter(),
    ("transport", "mt3dms"): Mt3dmsTransportAdapter(),
    ("transport", "modflow6gwt"): Modflow6GwtTransportAdapter(),
}


def get_solver_adapter(process_type: str, solver_name: str) -> SolverAdapter:
    """Return the adapter registered for one ``(process_type, solver_name)`` pair."""

    key = (process_type, solver_name)
    if key not in _ADAPTERS:
        raise ValueError(
            f"Unsupported simulation process/solver pair: {process_type}/{solver_name}."
        )
    return _ADAPTERS[key]
