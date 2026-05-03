"""Protocol for read-only solver-registry access across layers."""

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

    def get_extractor_instance(self, solver_name: str) -> Any | None:
        """Return a freshly-instantiated extractor, or None when unknown."""


__all__ = ("SolverRegistryProvider",)
