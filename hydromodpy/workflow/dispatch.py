"""Which workflow a configuration file runs.

A file names its workflow with ``[workflow] mode``. Left unwritten, the mode
follows from the sections the file carries: ``[calibration]`` calibrates,
``[overview]`` without ``[simulation]`` draws the data overview, anything else
simulates. :func:`infer_workflow` is the one place that rule is written, and
:func:`resolve_workflow` applies it to a file, so ``hmp run`` and ``hmp.run``
read a file the same way.

The modes of the retired orchestrators (``comparison``, ``testbed``) are refused with their replacement, the same sentence the
configuration model gives (:data:`hydromodpy.config.hydromodpy_config.RETIRED_WORKFLOW_MODES`).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, get_args

from hydromodpy.config.hydromodpy_config import RETIRED_WORKFLOW_MODES, WorkflowMode
from hydromodpy.core.exceptions import ConfigError

WorkflowName = WorkflowMode

KNOWN_WORKFLOWS: tuple[str, ...] = get_args(WorkflowMode)


class WorkflowError(ConfigError):
    """Base class for workflow-dispatch errors."""


class WorkflowUnknownError(WorkflowError):
    """The file declares a workflow mode that does not exist."""


class WorkflowMismatchError(WorkflowError):
    """The requested workflow and the one the file declares disagree."""


def load_raw_toml(config_path: Path) -> dict[str, Any]:
    """Parse a TOML config file with recursive ``base_config`` inheritance."""
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    return load_toml_with_base_config(config_path)


def extract_workflow_field(raw_toml: Mapping[str, Any]) -> str | None:
    """Return ``[workflow] mode``, or None when the file leaves it unwritten."""
    section = raw_toml.get("workflow")
    if section is None:
        return None
    if not isinstance(section, Mapping):
        raise WorkflowUnknownError(f"TOML [workflow] must be a table, got {type(section).__name__}")
    value = section.get("mode")
    if value is None:
        return None
    if not isinstance(value, str):
        raise WorkflowUnknownError(
            f"TOML 'workflow.mode' must be a string, got {type(value).__name__}"
        )
    return value


def infer_workflow(*, calibration: bool, overview: bool, simulation: bool) -> WorkflowName:
    """Return the workflow the sections of a file imply.

    ``[calibration]`` wins, then ``[overview]`` when no ``[simulation]`` table
    says otherwise, then a simulation.
    """
    if calibration:
        return "calibration"
    if overview and not simulation:
        return "overview"
    return "simulation"


def workflow_of_sections(raw_toml: Mapping[str, Any]) -> WorkflowName:
    """Return the workflow a raw TOML document implies by its sections."""
    return infer_workflow(
        calibration="calibration" in raw_toml,
        overview="overview" in raw_toml,
        simulation="simulation" in raw_toml,
    )


def check_workflow_name(value: str) -> WorkflowName:
    """Return *value* as a workflow name, or refuse it with the replacement when retired."""
    if value in RETIRED_WORKFLOW_MODES:
        raise WorkflowUnknownError(RETIRED_WORKFLOW_MODES[value])
    if value not in KNOWN_WORKFLOWS:
        raise WorkflowUnknownError(
            f"TOML 'workflow.mode' value {value!r} is not one of "
            f"{', '.join(repr(w) for w in KNOWN_WORKFLOWS)}"
        )
    return value  # type: ignore[return-value]


def resolve_workflow(config_path: Path, *, cli_workflow: str | None = None) -> WorkflowName:
    """Return the workflow of a file: its declared mode, or the one its sections imply.

    A caller that already chose a workflow (``cli_workflow``) must agree with
    the file when the file declares one.
    """
    raw = load_raw_toml(config_path)
    declared = extract_workflow_field(raw)
    toml_workflow = check_workflow_name(declared) if declared is not None else None

    if cli_workflow is not None:
        requested = check_workflow_name(cli_workflow)
        if toml_workflow is not None and requested != toml_workflow:
            raise WorkflowMismatchError(
                f"CLI subcommand selected workflow={requested!r} but "
                f"{config_path.name} declares workflow={toml_workflow!r}. "
                f"Fix one of the two so they agree."
            )
        return requested
    if toml_workflow is not None:
        return toml_workflow
    return workflow_of_sections(raw)


__all__ = (
    "KNOWN_WORKFLOWS",
    "WorkflowError",
    "WorkflowMismatchError",
    "WorkflowName",
    "WorkflowUnknownError",
    "check_workflow_name",
    "extract_workflow_field",
    "infer_workflow",
    "load_raw_toml",
    "resolve_workflow",
    "workflow_of_sections",
)
