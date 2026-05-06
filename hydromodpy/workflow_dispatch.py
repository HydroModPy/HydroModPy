"""Public workflow dispatch adapters.

This root-level module wires user-facing entry points to workflow launchers.
It is allowed to depend on :class:`hydromodpy.project.Project`; the lower
``hydromodpy.workflow`` package remains independent from that facade.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.dispatch import (
    run_batch,
    run_calibration,
    run_comparison,
    run_mesh,
    run_overview,
)


def run_simulation(
    config_path: str | Path,
    *,
    resume: str | None = None,
    from_step: str | int | None = None,
    until_step: str | int | None = None,
    checkpoint: bool = False,
    no_checkpoint: bool = False,
    no_display: bool = False,
    frozen: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute a single simulation from a TOML file."""
    from hydromodpy.project import Project

    resume_options_used = resume is not None or from_step is not None or until_step is not None
    if no_checkpoint and resume_options_used:
        raise ConfigError("Resume options require checkpoint persistence.")
    checkpoint_enabled = bool(checkpoint or resume_options_used) and not no_checkpoint

    with Project(config_path, no_display=no_display) as project:
        result = project.run(
            checkpoint=checkpoint_enabled,
            resume=resume,
            from_step=from_step,
            until_step=until_step,
            dry_run=dry_run,
            frozen=frozen,
            no_display=no_display,
        )
        if result is None:
            return {}
        return {
            "name": result.name,
            "sim_id": result.sim_id,
        }


class ProjectTestbedRunnerProvider:
    """Testbed runner provider backed by public workflow adapters."""

    def run_mesh_catchment(self, config_path: Path) -> Mapping[str, Any]:
        """Run one mesh-catchment child configuration."""
        return dict(run_mesh(config_path))

    def run_simulation(self, config_path: Path, *, no_display: bool) -> Mapping[str, Any]:
        """Run one simulation child configuration."""
        return dict(run_simulation(config_path, no_display=no_display))


def run_testbed(config_path: str | Path) -> dict[str, Any]:
    """Run a method-testbed workflow from a TOML file."""
    from hydromodpy.analysis.testbed.contracts import register_testbed_runner_provider
    from hydromodpy.analysis.testbed.runtime import TestbedLauncher

    register_testbed_runner_provider(ProjectTestbedRunnerProvider())
    return TestbedLauncher(config_path).run()


DISPATCH: dict[str, Callable[..., dict[str, Any]]] = {
    "simulation": run_simulation,
    "overview": run_overview,
    "mesh": run_mesh,
    "calibration": run_calibration,
    "batch": run_batch,
    "comparison": run_comparison,
    "testbed": run_testbed,
}


def dispatch_workflow(workflow: str, config_path: Path, **kwargs: Any) -> dict[str, Any]:
    """Dispatch to the adapter for a resolved workflow name."""
    runner = DISPATCH[workflow]
    return runner(config_path, **kwargs)


__all__ = [
    "DISPATCH",
    "ProjectTestbedRunnerProvider",
    "dispatch_workflow",
    "run_batch",
    "run_calibration",
    "run_comparison",
    "run_mesh",
    "run_overview",
    "run_simulation",
    "run_testbed",
]
