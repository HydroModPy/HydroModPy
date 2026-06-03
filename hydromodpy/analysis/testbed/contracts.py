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

    def run_calibration(self, config_path: Path) -> Mapping[str, Any]:
        """Run one calibration child configuration."""


@runtime_checkable
class TestbedWorkflowAdapter(Protocol):
    """Workflow-specific execution adapter used by the testbed runtime."""

    runner_type: str
    workflow: str

    def run(
        self,
        provider: TestbedRunnerProvider,
        config_path: Path,
        *,
        no_display: bool,
    ) -> Mapping[str, Any]:
        """Run one child workflow through the provided runner bundle."""


class SimulationTestbedWorkflowAdapter:
    """Default adapter for simulation child workflows."""

    runner_type = "simulation"
    workflow = "simulation"

    def run(
        self,
        provider: TestbedRunnerProvider,
        config_path: Path,
        *,
        no_display: bool,
    ) -> Mapping[str, Any]:
        return provider.run_simulation(config_path, no_display=no_display)


class ComparisonTestbedWorkflowAdapter:
    """Default adapter for comparison child workflows."""

    runner_type = "comparison"
    workflow = "comparison"

    def run(
        self,
        provider: TestbedRunnerProvider,
        config_path: Path,
        *,
        no_display: bool,
    ) -> Mapping[str, Any]:
        return provider.run_comparison(config_path)


class CalibrationTestbedWorkflowAdapter:
    """Default adapter for calibration child workflows."""

    runner_type = "calibration"
    workflow = "calibration"

    def run(
        self,
        provider: TestbedRunnerProvider,
        config_path: Path,
        *,
        no_display: bool,
    ) -> Mapping[str, Any]:
        return provider.run_calibration(config_path)


_provider: TestbedRunnerProvider | None = None
_workflow_adapters: dict[str, TestbedWorkflowAdapter] = {
    "calibration": CalibrationTestbedWorkflowAdapter(),
    "comparison": ComparisonTestbedWorkflowAdapter(),
    "simulation": SimulationTestbedWorkflowAdapter(),
}


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
            "executing testbed cases."
        )
    return _provider


def register_testbed_workflow_adapter(adapter: TestbedWorkflowAdapter) -> None:
    """Register or replace one testbed workflow adapter."""
    runner_type = str(adapter.runner_type).strip().lower()
    if not runner_type:
        raise ValueError("testbed workflow adapter runner_type cannot be empty")
    _workflow_adapters[runner_type] = adapter


def get_testbed_workflow_adapter(runner_type: str) -> TestbedWorkflowAdapter:
    """Return the adapter registered for one testbed runner type."""
    normalized = str(runner_type).strip().lower()
    try:
        return _workflow_adapters[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported testbed runner: {runner_type}") from exc


def available_testbed_runner_types() -> tuple[str, ...]:
    """Return registered runner types in stable order."""
    return tuple(sorted(_workflow_adapters))


def testbed_runner_workflow(runner_type: str) -> str:
    """Return the child workflow mode associated with one testbed runner type."""
    return get_testbed_workflow_adapter(runner_type).workflow


def run_testbed_child_workflow(
    *,
    runner_type: str,
    config_path: Path,
    no_display: bool = False,
) -> Mapping[str, Any]:
    """Run one child workflow through the registered testbed provider."""
    provider = get_testbed_runner_provider()
    adapter = get_testbed_workflow_adapter(runner_type)
    return adapter.run(provider, config_path, no_display=no_display)


__all__ = [
    "CalibrationTestbedWorkflowAdapter",
    "ComparisonTestbedWorkflowAdapter",
    "SimulationTestbedWorkflowAdapter",
    "TestbedRunnerProvider",
    "TestbedWorkflowAdapter",
    "available_testbed_runner_types",
    "get_testbed_runner_provider",
    "get_testbed_workflow_adapter",
    "register_testbed_runner_provider",
    "register_testbed_workflow_adapter",
    "run_testbed_child_workflow",
    "testbed_runner_workflow",
]
