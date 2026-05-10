"""Workflow runner contracts consumed by method testbeds."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TestbedRunnerProvider(Protocol):
    """Child workflow runner bundle consumed by testbed launchers."""

    def run_simulation(self, config_path: Path, *, no_display: bool) -> Mapping[str, Any]:
        """Run one simulation child configuration."""

    def run_comparison(self, config_path: Path) -> Mapping[str, Any]:
        """Run one comparison child configuration."""


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


def run_testbed_child_workflow(
    *,
    runner_type: str,
    config_path: Path,
    no_display: bool = False,
) -> Mapping[str, Any]:
    """Run one child workflow through the registered testbed provider."""
    provider = get_testbed_runner_provider()
    if runner_type == "simulation":
        return provider.run_simulation(config_path, no_display=no_display)
    if runner_type == "comparison":
        return provider.run_comparison(config_path)
    raise ValueError(f"Unsupported testbed runner: {runner_type}")


__all__ = [
    "TestbedRunnerProvider",
    "get_testbed_runner_provider",
    "register_testbed_runner_provider",
    "run_testbed_child_workflow",
]
