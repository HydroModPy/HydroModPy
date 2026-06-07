"""Solver-registry Protocol and module-level provider singleton.

The 15x15 layer matrix forbids ``simulation -> solver`` and
``analysis -> solver``. Planning, the runner, post-run ingestion,
transport helpers, and comparison launchers reach the solver registry
through :class:`SolverRegistryProvider`. The concrete provider is wired
in at package bootstrap by :mod:`hydromodpy._bootstrap`.

The singleton state lives here (in ``core``) to give simulation and
analysis a single source of truth for the installed provider, instead
of two parallel singletons. The getter raises when the provider is
missing: every consumer is critical enough that silently returning
``None`` would mask bootstrap regressions.
"""

from __future__ import annotations

from typing import Any, Protocol


class SolverRegistryProvider(Protocol):
    """Read-only view of the solver registry consumed outside solver."""

    def distributed_flow_solver_sections(self) -> tuple[str, ...]:
        """Return the TOML section names of distributed flow solvers."""

    def known_process_types(self) -> set[str]:
        """Return the process types declared by registered adapters."""

    def required_bindings(self, process_type: str, solver_name: str) -> tuple[tuple[str, str], ...]:
        """Return capabilities required by earlier runs."""

    def get_solver_adapter(self, process_type: str, solver_name: str) -> Any:
        """Return a freshly-instantiated adapter for the given pair."""

    def get_solver_adapter_class(self, process_type: str, solver_name: str) -> type:
        """Return the adapter class registered for the given pair."""

    def get_extractor_instance(self, process_type: str, solver_name: str) -> Any | None:
        """Return a freshly-instantiated extractor, or None when unknown."""


_PROVIDER: SolverRegistryProvider | None = None


def set_solver_registry_provider(provider: SolverRegistryProvider) -> None:
    """Install the registry provider used by simulation and analysis."""
    global _PROVIDER
    _PROVIDER = provider


def get_solver_registry_provider() -> SolverRegistryProvider:
    """Return the installed provider.

    Raises ``RuntimeError`` when the bootstrap has not run yet, since
    every consumer (simulation runner, planner, comparison launchers)
    cannot operate without a backing solver registry.
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
