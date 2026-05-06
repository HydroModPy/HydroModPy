"""Workflow dispatch helpers."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal

from hydromodpy.core.exceptions import ConfigError

WorkflowName = Literal[
    "simulation",
    "calibration",
    "batch",
    "overview",
    "mesh",
    "comparison",
    "testbed",
]

KNOWN_WORKFLOWS: tuple[str, ...] = (
    "simulation",
    "calibration",
    "batch",
    "overview",
    "mesh",
    "comparison",
    "testbed",
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


def run_comparison(config_path: str | Path) -> dict[str, Any]:
    """Run a comparison workflow from a TOML file."""
    from hydromodpy.analysis.comparison.dispatch import run_comparison_config

    return run_comparison_config(config_path)


__all__ = (
    "KNOWN_WORKFLOWS",
    "WorkflowError",
    "WorkflowMismatchError",
    "WorkflowMissingError",
    "WorkflowName",
    "WorkflowUnknownError",
    "extract_workflow_field",
    "load_raw_toml",
    "resolve_workflow",
    "run_batch",
    "run_calibration",
    "run_comparison",
    "run_mesh",
    "run_overview",
)
