"""Workflow runner contracts consumed by method testbeds."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TestbedRunnerProvider(Protocol):
    """Child workflow runner bundle consumed by testbed launchers."""

    def run_mesh_catchment(self, config_path: Path) -> Mapping[str, Any]:
        """Run one mesh-catchment child configuration."""

    def run_simulation(self, config_path: Path, *, no_display: bool) -> Mapping[str, Any]:
        """Run one simulation child configuration."""


_provider: TestbedRunnerProvider | None = None


def register_testbed_runner_provider(provider: TestbedRunnerProvider) -> None:
    """Register the workflow-backed runner provider."""
    global _provider
    _provider = provider


def get_testbed_runner_provider() -> TestbedRunnerProvider:
    """Return the registered runner provider, or raise if none is wired."""
    if _provider is None:
        raise RuntimeError(
            "TestbedRunnerProvider is not registered. "
            "Import 'hydromodpy' (or call hydromodpy.bootstrap()) before "
            "executing testbed variants."
        )
    return _provider


__all__ = [
    "TestbedRunnerProvider",
    "get_testbed_runner_provider",
    "register_testbed_runner_provider",
]
