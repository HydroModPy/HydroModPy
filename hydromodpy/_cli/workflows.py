"""Workflow dispatch helpers for ``hmp run``.

Absorbs the ex-``hydromodpy.runners`` thin shells: each workflow type has a
``run_*`` function that loads a TOML and hands it to its domain pipeline.
``detect_workflow`` is the canonical helper mapping TOML sections to a
workflow label.
"""

from __future__ import annotations

from pathlib import Path


def detect_workflow(raw_toml: dict) -> str:
    """Determine workflow type from top-level TOML sections.

    Returns one of: ``"calibration"``, ``"batch"``, ``"overview"``,
    ``"mesh"``, ``"simulation"``.
    """
    if "calibration" in raw_toml:
        return "calibration"
    if "batch" in raw_toml:
        return "batch"
    if "overview" in raw_toml and "simulation" not in raw_toml:
        return "overview"
    if "mesh_catchment" in raw_toml and "simulation" not in raw_toml:
        return "mesh"
    return "simulation"


# ---------------------------------------------------------------------------
# Workflow adapters (ex-runners/*.py)
# ---------------------------------------------------------------------------


def run_simulation(config_path: str | Path, *, resume: str | None = None) -> dict:
    """Execute a single simulation from a TOML file."""
    if resume is not None:
        return _run_resume(Path(config_path), resume)

    from hydromodpy.project import Simulation

    with Simulation(config_path) as project:
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


WORKFLOW_DISPATCH: dict[str, str] = {
    "simulation": "hydromodpy._cli.workflows:run_simulation",
    "overview": "hydromodpy._cli.workflows:run_overview",
    "mesh": "hydromodpy._cli.workflows:run_mesh",
    "calibration": "hydromodpy._cli.workflows:run_calibration",
    "batch": "hydromodpy._cli.workflows:run_batch",
}


def _run_resume(config_path: Path, run_id: str) -> dict:
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

    initial = PipelineState(run_id=run_id, data={"config_path": config_path})
    pipeline = Pipeline(
        standard_steps(), workspace=workspace, checkpoint=True,
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
        if (parent / "hydromodpy.duckdb").exists() or (
            parent / ".hmp"
        ).is_dir():
            return parent
    return config_path.parent


__all__ = (
    "detect_workflow",
    "run_simulation",
    "run_overview",
    "run_mesh",
    "run_calibration",
    "run_batch",
    "WORKFLOW_DISPATCH",
)
