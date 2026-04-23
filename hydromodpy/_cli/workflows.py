"""Workflow dispatch helpers.

Single CLI entry point: ``hmp run <toml>``. The TOML must declare a
mandatory top-level ``workflow = "..."`` field (one of ``simulation``,
``calibration``, ``batch``, ``overview``, ``mesh``). Dispatches to the
matching ``run_*`` adapter.

The contract is enforced twice: here at CLI load time via
:func:`resolve_workflow` for friendly error messages, and again at the
Pydantic layer (:class:`hydromodpy.core.config.HydroModPyConfig`) so
API-driven callers (e.g. an Angular frontend posting a serialised
config) face the same contract as the CLI.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

WorkflowName = Literal["simulation", "calibration", "batch", "overview", "mesh"]

KNOWN_WORKFLOWS: tuple[str, ...] = (
    "simulation",
    "calibration",
    "batch",
    "overview",
    "mesh",
)


class WorkflowError(Exception):
    """Base class for workflow-dispatch errors surfaced to the CLI user."""


class WorkflowMissingError(WorkflowError):
    """TOML lacks the top-level ``workflow`` field required by ``hmp run``."""


class WorkflowUnknownError(WorkflowError):
    """TOML declares ``workflow = "..."`` but the value is not recognised."""


class WorkflowMismatchError(WorkflowError):
    """CLI subcommand and TOML ``workflow`` field disagree."""


# ---------------------------------------------------------------------------
# TOML loading + validation
# ---------------------------------------------------------------------------


def load_raw_toml(config_path: Path) -> dict:
    """Parse ``config_path`` as TOML, return raw dict."""
    with open(config_path, "rb") as fh:
        return tomllib.load(fh)


def extract_workflow_field(raw_toml: dict) -> str | None:
    """Return the top-level ``workflow = "..."`` field or ``None`` if absent."""
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
    """Resolve which workflow to run and validate CLI↔TOML consistency.

    Parameters
    ----------
    config_path
        Path to the TOML config.
    cli_workflow
        Workflow name from the CLI subcommand (e.g. ``"simulation"`` when the
        user invoked ``hmp simulate``), or ``None`` for ``hmp run``.
    require_toml_field
        If ``True``, the TOML MUST declare ``workflow = "..."`` - else
        :class:`WorkflowMissingError`. Set by ``hmp run``.

    Returns
    -------
    The validated workflow name.

    Raises
    ------
    WorkflowMissingError
        Generic ``hmp run`` but TOML lacks ``workflow = "..."``.
    WorkflowUnknownError
        TOML declares a ``workflow`` value outside :data:`KNOWN_WORKFLOWS`.
    WorkflowMismatchError
        Explicit CLI subcommand and TOML field disagree.
    """
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

    if cli_workflow is not None and toml_workflow is not None:
        if cli_workflow != toml_workflow:
            raise WorkflowMismatchError(
                f"CLI subcommand selected workflow={cli_workflow!r} but "
                f"{config_path.name} declares workflow={toml_workflow!r}. "
                f"Fix one of the two so they agree."
            )

    # Priority: CLI > TOML (they are either equal or one is None at this point)
    return cli_workflow or toml_workflow  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Workflow adapters
# ---------------------------------------------------------------------------


def run_simulation(
    config_path: str | Path,
    *,
    resume: str | None = None,
    no_display: bool = False,
) -> dict:
    """Execute a single simulation from a TOML file."""
    if resume is not None:
        return _run_resume(Path(config_path), resume, no_display=no_display)

    from hydromodpy.project import Project

    with Project(config_path, no_display=no_display) as project:
        result = project.run()
        return {
            "name": result.name,
            "sim_id": result.sim_id,
        }


def run_overview(config_path: str | Path) -> dict:
    """Generate a watershed identity card from a TOML file."""
    from hydromodpy.workflow.pipelines.overview import DataOverviewLauncher

    return DataOverviewLauncher(config_path).run()


def run_mesh(config_path: str | Path) -> dict:
    """Generate a catchment mesh from a TOML file."""
    from hydromodpy.workflow.pipelines.mesh import MeshCatchmentLauncher

    return MeshCatchmentLauncher(config_path).run()


def run_calibration(config_path: str | Path) -> dict:
    """Run a parameter calibration campaign from a TOML file."""
    from hydromodpy.calibration.cli import run_calibration_cli

    return run_calibration_cli(config_path)


def run_batch(config_path: str | Path) -> dict:
    """Run a multi-site batch campaign from a TOML file."""
    from hydromodpy.analysis.batch.runtime import RegionalLabLauncher

    return RegionalLabLauncher(config_path).run()


DISPATCH: dict[str, callable] = {
    "simulation": run_simulation,
    "overview": run_overview,
    "mesh": run_mesh,
    "calibration": run_calibration,
    "batch": run_batch,
}


def dispatch_workflow(workflow: str, config_path: Path, **kwargs) -> dict:
    """Dispatch to the ``run_*`` adapter for a resolved workflow name."""
    runner = DISPATCH[workflow]
    return runner(config_path, **kwargs)


# Legacy alias - retained for callers that imported the old name. Identical
# semantics: maps a workflow label to a "module:fn" string.
WORKFLOW_DISPATCH: dict[str, str] = {
    "simulation": "hydromodpy._cli.workflows:run_simulation",
    "overview": "hydromodpy._cli.workflows:run_overview",
    "mesh": "hydromodpy._cli.workflows:run_mesh",
    "calibration": "hydromodpy._cli.workflows:run_calibration",
    "batch": "hydromodpy._cli.workflows:run_batch",
}


def _run_resume(config_path: Path, run_id: str, *, no_display: bool = False) -> dict:
    """Resume a previously interrupted simulation via the new Pipeline."""
    from hydromodpy.pipeline import Pipeline, PipelineState
    from hydromodpy.pipeline.checkpoint import CheckpointStore
    from hydromodpy.pipeline.ledger import StepsLedger
    from hydromodpy.pipeline.steps import standard_steps

    workspace = _resolve_workspace_for_resume(config_path)
    cp = CheckpointStore(workspace, run_id)
    last = cp.latest()
    if last is None:
        raise RuntimeError(
            f"No checkpoints found for run_id '{run_id}' in {cp.dir}. "
            "Start a fresh run instead of using --resume."
        )
    resume_from = last + 1

    ledger = StepsLedger(workspace)
    last_completed = ledger.last_completed(run_id)
    ledger.close()
    if last_completed is not None:
        resume_from = max(resume_from, last_completed + 1)

    initial = PipelineState(
        run_id=run_id,
        data={"config_path": config_path, "skip_display": no_display},
    )
    pipeline = Pipeline(
        standard_steps(),
        workspace=workspace,
        checkpoint=True,
    )
    final = pipeline.run(initial, resume_from=resume_from)
    ctx = final.get("ctx")
    return {
        "run_id": run_id,
        "resumed_from": resume_from,
        "sim_id": getattr(ctx, "sim_id", None) if ctx is not None else None,
    }


def _resolve_workspace_for_resume(config_path: Path) -> Path:
    """Walk up from ``config_path`` to find a workspace root."""
    for parent in [config_path.parent, *config_path.parents]:
        if (parent / "hydromodpy.duckdb").exists() or (parent / ".hmp").is_dir():
            return parent
    return config_path.parent


__all__ = (
    "KNOWN_WORKFLOWS",
    "WorkflowError",
    "WorkflowMissingError",
    "WorkflowUnknownError",
    "WorkflowMismatchError",
    "load_raw_toml",
    "extract_workflow_field",
    "resolve_workflow",
    "dispatch_workflow",
    "run_simulation",
    "run_overview",
    "run_mesh",
    "run_calibration",
    "run_batch",
    "WORKFLOW_DISPATCH",
    "DISPATCH",
)
