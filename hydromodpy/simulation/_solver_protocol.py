"""Protocol decoupling simulation orchestration from the solver registry.

The 14x14 layer matrix forbids ``simulation -> solver``. Planning, the
runner, post-run ingestion and transport helpers however need to query
the solver registry to: list the registered process types, resolve a
pair's prerequisites, instantiate an adapter, look up an extractor.
They consume that information through this Protocol; the concrete
provider is wired in at package bootstrap by :mod:`hydromodpy._bootstrap`.

This is the same pattern already used by
:mod:`hydromodpy.analysis.comparison._solver_protocol`.
"""

from __future__ import annotations

from typing import Any, Protocol


class SolverRegistryProvider(Protocol):
    """Read-only view of the solver registry consumed by simulation."""

    def known_process_types(self) -> set[str]:
        """Return the set of process types declared by any registered adapter."""

    def required_bindings(self, process_type: str, solver_name: str) -> tuple[tuple[str, str], ...]:
        """Return capabilities that must be satisfied by earlier runs."""

    def get_solver_adapter(self, process_type: str, solver_name: str) -> Any:
        """Return a freshly-instantiated adapter for the given pair."""

    def get_solver_adapter_class(self, process_type: str, solver_name: str) -> type:
        """Return the adapter **class** registered for the given pair."""

    def get_extractor_instance(self, solver_name: str) -> Any | None:
        """Return a freshly-instantiated extractor, or ``None`` when unknown."""


_PROVIDER: SolverRegistryProvider | None = None


def set_solver_registry_provider(provider: SolverRegistryProvider) -> None:
    """Install the registry provider used by simulation."""
    global _PROVIDER
    _PROVIDER = provider


def get_solver_registry_provider() -> SolverRegistryProvider:
    """Return the installed provider.

    Raises ``RuntimeError`` when the bootstrap has not run yet, since
    simulation cannot operate without a backing solver registry.
    """
    if _PROVIDER is None:
        raise RuntimeError(
            "Solver registry provider not installed. "
            "Did you forget to import hydromodpy (which calls bootstrap())?"
        )
    return _PROVIDER


__all__ = (
    "SolverRegistryProvider",
    "get_solver_registry_provider",
    "set_solver_registry_provider",
)
