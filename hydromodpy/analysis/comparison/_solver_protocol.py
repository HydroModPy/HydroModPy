"""Protocol decoupling analysis comparison helpers from the solver registry.

Analysis cannot import the solver layer (cf. layer matrix). Comparison
code that needs to enumerate distributed flow solver sections receives
the lookup through this Protocol; the concrete provider is registered
at package bootstrap by a higher layer (see ``hydromodpy/_bootstrap.py``).
"""

from __future__ import annotations

from hydromodpy.core.contracts.solver_registry import SolverRegistryProvider

_PROVIDER: SolverRegistryProvider | None = None


def set_solver_registry_provider(provider: SolverRegistryProvider) -> None:
    """Install the registry provider used by comparison helpers."""
    global _PROVIDER
    _PROVIDER = provider


def get_solver_registry_provider() -> SolverRegistryProvider | None:
    """Return the installed provider, or ``None`` when none has been set."""
    return _PROVIDER


__all__ = (
    "SolverRegistryProvider",
    "get_solver_registry_provider",
    "set_solver_registry_provider",
)
