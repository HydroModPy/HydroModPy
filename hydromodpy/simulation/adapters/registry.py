"""Thin shim that registers built-in simulation adapters with the canonical
``hydromodpy.solver.base.registry``.

The merger is documented in ``architecture_cible/05_solver_contracts.md``
§4: there is now a single registry of solver adapter classes. This module
exists for two reasons:

1. **Eager registration of in-tree adapters.** Importing
   ``hydromodpy.simulation.adapters`` populates the canonical registry with
   the six concrete classes shipped in the codebase (flow / transport).
2. **Compatibility shim** for callers that still import
   ``get_solver_adapter`` / ``register_adapter`` from this module. Both
   functions delegate to the canonical registry.

External plugin packages should declare adapters via the
``hydromodpy.solver`` entry-points group, see
:func:`hydromodpy.solver.base.registry.load_plugins`.
"""

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
from hydromodpy.solver.base import registry as _canonical

_BUILTIN_ADAPTERS: tuple[tuple[str, str, type], ...] = (
    ("flow", "modflownwt", ModflowNwtFlowAdapter),
    ("flow", "modflow6", Modflow6FlowAdapter),
    ("flow", "boussinesq", BoussinesqFlowAdapter),
    ("transport", "modpath", ModpathTransportAdapter),
    ("transport", "mt3dms", Mt3dmsTransportAdapter),
    ("transport", "modflow6gwt", Modflow6GwtTransportAdapter),
)


def _register_builtins() -> None:
    """Idempotently register the in-tree adapter classes with the canonical
    registry. Safe to call from imports: re-registration is a no-op."""
    for process_type, solver_name, adapter_cls in _BUILTIN_ADAPTERS:
        if (process_type, solver_name) in _canonical._REGISTRY:
            continue
        _canonical.register(process_type, solver_name, adapter_cls)


_register_builtins()


def register_adapter(
    process_type: str,
    solver_name: str,
    adapter: SolverRunner | type,
) -> None:
    """Register a solver adapter (instance or class) for the given pair.

    Accepting an instance preserves the legacy v0.4 calling convention; the
    class is recovered from ``type(adapter)`` and stored in the canonical
    registry. Pure-class registration is also supported.
    """
    cls = adapter if isinstance(adapter, type) else type(adapter)
    _canonical.register(process_type, solver_name, cls)


def get_solver_adapter(process_type: str, solver_name: str) -> SolverRunner:
    """Return a fresh adapter instance for ``(process_type, solver_name)``.

    Delegates to :func:`hydromodpy.solver.base.registry.get_solver_adapter`.
    Raises ``ValueError`` (matching the historical contract) when no
    adapter is registered for the requested pair.
    """
    try:
        return _canonical.get_solver_adapter(process_type, solver_name)
    except KeyError as exc:
        raise ValueError(str(exc)) from exc


__all__ = ["get_solver_adapter", "register_adapter"]
