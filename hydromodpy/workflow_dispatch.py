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


def run_overview(config_path: str | Path) -> dict[str, Any]:
    """Generate a watershed identity card from a TOML file."""
    from hydromodpy.workflow.pipelines.overview import DataOverviewLauncher

    return DataOverviewLauncher(config_path).run()


def run_calibration(config_path: str | Path) -> dict[str, Any]:
    """Run a parameter calibration campaign from a TOML file."""
    from hydromodpy.calibration.runner import run_calibration_cli

    return run_calibration_cli(config_path)


def run_comparison(config_path: str | Path) -> dict[str, Any]:
    """Run a comparison workflow from a TOML file."""
    from hydromodpy.analysis.comparison.dispatch import run_comparison_config

    return run_comparison_config(config_path)


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
        summary = {
            "name": result.name,
            "sim_id": result.sim_id,
        }
        project_ctx = getattr(project, "_ctx", None)
        project_setup = getattr(project_ctx, "setup", None)
        project_plan = getattr(getattr(project_ctx, "execution", None), "simulation_plan", None)
        mesh_summary = getattr(project_setup, "mesh_summary", None)
        has_mesh_process = any(
            getattr(run, "process_type", None) == "mesh"
            for run in getattr(project_plan, "runs", ()) or ()
        )
        if has_mesh_process and isinstance(mesh_summary, Mapping):
            summary.update(dict(mesh_summary))
        return summary


class ProjectTestbedRunnerProvider:
    """Testbed runner provider backed by public workflow adapters."""

    def run_simulation(self, config_path: Path, *, no_display: bool) -> Mapping[str, Any]:
        """Run one simulation child configuration."""
        return dict(run_simulation(config_path, no_display=no_display))

    def run_comparison(self, config_path: Path) -> Mapping[str, Any]:
        """Run one comparison child configuration."""
        return dict(run_comparison(config_path))


def run_testbed(config_path: str | Path) -> dict[str, Any]:
    """Run a method-testbed workflow from a TOML file."""
    from hydromodpy.analysis.testbed.profiles import (
        GENERIC_TESTBED_PROFILE,
        REGIONAL_LAB_PROFILE,
        resolve_testbed_profile,
    )
    from hydromodpy.analysis.testbed.runtime import TestbedLauncher
    from hydromodpy.core.toml_io import load_toml_with_base_config

    raw_toml = load_toml_with_base_config(Path(config_path).expanduser().resolve())
    profile = resolve_testbed_profile(raw_toml)
    if profile == REGIONAL_LAB_PROFILE:
        from hydromodpy.analysis.testbed.regional_lab import RegionalLabProfileLauncher

        return RegionalLabProfileLauncher(config_path).run()
    if profile != GENERIC_TESTBED_PROFILE:
        raise ValueError(f"Unsupported testbed profile: {profile}")
    return TestbedLauncher(config_path).run()


DISPATCH: dict[str, Callable[..., dict[str, Any]]] = {
    "simulation": run_simulation,
    "overview": run_overview,
    "calibration": run_calibration,
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
    "run_calibration",
    "run_comparison",
    "run_overview",
    "run_simulation",
    "run_testbed",
]
