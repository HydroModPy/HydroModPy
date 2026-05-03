"""Workflow-backed runner provider for method testbeds."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.analysis.testbed.contracts import (
    TestbedRunnerProvider,
    register_testbed_runner_provider,
)


class WorkflowTestbedRunnerProvider(TestbedRunnerProvider):
    """Concrete testbed runner provider backed by workflow launchers."""

    def run_mesh_catchment(self, config_path: Path) -> Mapping[str, Any]:
        """Run one mesh-catchment child configuration."""
        from hydromodpy.workflow.pipelines.mesh import MeshCatchmentLauncher

        return dict(MeshCatchmentLauncher(config_path).run())

    def run_simulation(self, config_path: Path, *, no_display: bool) -> Mapping[str, Any]:
        """Run one simulation child configuration."""
        from hydromodpy.workflow.dispatch import run_simulation

        return dict(run_simulation(config_path, no_display=no_display))


def register_default_testbed_runner_provider() -> None:
    """Register the workflow-backed testbed runner provider."""
    register_testbed_runner_provider(WorkflowTestbedRunnerProvider())


__all__ = [
    "WorkflowTestbedRunnerProvider",
    "register_default_testbed_runner_provider",
]
