"""Workflow dispatch helpers."""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from hydromodpy.core.exceptions import ConfigError

WorkflowName = Literal[
    "simulation",
    "calibration",
    "batch",
    "overview",
    "mesh",
    "method-comparison",
]

KNOWN_WORKFLOWS: tuple[str, ...] = (
    "simulation",
    "calibration",
    "batch",
    "overview",
    "mesh",
    "method-comparison",
)


class WorkflowError(ConfigError):
    """Base class for workflow-dispatch errors."""


class WorkflowMissingError(WorkflowError):
    """TOML lacks the top-level workflow field."""


class WorkflowUnknownError(WorkflowError):
    """TOML declares an unknown workflow value."""


class WorkflowMismatchError(WorkflowError):
    """Requested workflow and TOML workflow field disagree."""


def load_raw_toml(config_path: Path) -> dict[str, Any]:
    """Parse a TOML config file."""
    with open(config_path, "rb") as fh:
        return tomllib.load(fh)


def extract_workflow_field(raw_toml: dict[str, Any]) -> str | None:
    """Return the top-level workflow field."""
    value = raw_toml.get("workflow")
    if value is None:
        return None
    if not isinstance(value, str):
        raise WorkflowUnknownError(f"TOML 'workflow' must be a string, got {type(value).__name__}")
    return value


def resolve_workflow(
    config_path: Path,
    *,
    cli_workflow: str | None,
    require_toml_field: bool,
) -> str:
    """Resolve and validate the workflow selected by config and caller."""
    raw = load_raw_toml(config_path)
    toml_workflow = extract_workflow_field(raw)

    if toml_workflow is not None and toml_workflow not in KNOWN_WORKFLOWS:
        raise WorkflowUnknownError(
            f"TOML 'workflow' value {toml_workflow!r} is not one of "
            f"{', '.join(repr(w) for w in KNOWN_WORKFLOWS)}"
        )

    if require_toml_field and toml_workflow is None:
        raise WorkflowMissingError(
            f"{config_path.name} must declare a top-level "
            f"'workflow = \"...\"' field.\n"
            f"Valid values: {', '.join(KNOWN_WORKFLOWS)}."
        )

    if cli_workflow is not None and toml_workflow is not None and cli_workflow != toml_workflow:
        raise WorkflowMismatchError(
            f"CLI subcommand selected workflow={cli_workflow!r} but "
            f"{config_path.name} declares workflow={toml_workflow!r}. "
            f"Fix one of the two so they agree."
        )

    if cli_workflow is not None:
        return cli_workflow
    if toml_workflow is None:
        raise WorkflowMissingError(
            f"{config_path.name} must declare a top-level "
            f"'workflow = \"...\"' field.\n"
            f"Valid values: {', '.join(KNOWN_WORKFLOWS)}."
        )
    return toml_workflow


def run_simulation(
    config_path: str | Path,
    *,
    resume: str | None = None,
    from_step: str | int | None = None,
    until_step: str | int | None = None,
    no_checkpoint: bool = False,
    no_display: bool = False,
    frozen: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute a single simulation from a TOML file."""
    from hydromodpy.project import Project

    with Project(config_path, no_display=no_display) as project:
        result = project.run(
            checkpoint=not no_checkpoint,
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


def run_overview(config_path: str | Path) -> dict[str, Any]:
    """Generate a watershed identity card from a TOML file."""
    from hydromodpy.workflow.pipelines.overview import DataOverviewLauncher

    return DataOverviewLauncher(config_path).run()


def run_mesh(config_path: str | Path) -> dict[str, Any]:
    """Generate a catchment mesh from a TOML file."""
    from hydromodpy.workflow.pipelines.mesh import MeshCatchmentLauncher

    return MeshCatchmentLauncher(config_path).run()


def run_calibration(config_path: str | Path) -> dict[str, Any]:
    """Run a parameter calibration campaign from a TOML file."""
    from hydromodpy.calibration.runner import run_calibration_cli

    return run_calibration_cli(config_path)


def run_batch(config_path: str | Path) -> dict[str, Any]:
    """Run a multi-site batch campaign from a TOML file."""
    from hydromodpy.analysis.batch.runtime import RegionalLabLauncher

    return RegionalLabLauncher(config_path).run()


def run_method_comparison(config_path: str | Path) -> dict[str, Any]:
    """Run a method-comparison workflow from a TOML file."""
    from hydromodpy.analysis.comparison.orchestrator import MethodComparisonLauncher

    return MethodComparisonLauncher(config_path).run()


DISPATCH: dict[str, Callable[..., dict[str, Any]]] = {
    "simulation": run_simulation,
    "overview": run_overview,
    "mesh": run_mesh,
    "calibration": run_calibration,
    "batch": run_batch,
    "method-comparison": run_method_comparison,
}


def dispatch_workflow(workflow: str, config_path: Path, **kwargs: Any) -> dict[str, Any]:
    """Dispatch to the adapter for a resolved workflow name."""
    runner = DISPATCH[workflow]
    return runner(config_path, **kwargs)


__all__ = (
    "DISPATCH",
    "KNOWN_WORKFLOWS",
    "WorkflowError",
    "WorkflowMismatchError",
    "WorkflowMissingError",
    "WorkflowName",
    "WorkflowUnknownError",
    "dispatch_workflow",
    "extract_workflow_field",
    "load_raw_toml",
    "resolve_workflow",
    "run_batch",
    "run_calibration",
    "run_mesh",
    "run_method_comparison",
    "run_overview",
    "run_simulation",
)
