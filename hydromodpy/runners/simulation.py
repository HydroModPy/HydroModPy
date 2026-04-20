"""CLI adapter for ``hmp run <config.toml>`` (simulation workflow).

Domain logic lives in :class:`hydromodpy.simulation.Simulation` and
``hydromodpy.workflow.pipelines.simulation``.

The ``--resume`` flag re-enters the new :class:`hydromodpy.pipeline.Pipeline`
orchestration: it restores the last checkpointed state for the given
``run_id`` and replays the remaining steps.
"""

from __future__ import annotations

from pathlib import Path


def run(config_path: str | Path, *, resume: str | None = None) -> dict:
    """Execute a single simulation from a TOML file.

    Parameters
    ----------
    config_path:
        Path to the TOML configuration.
    resume:
        If provided, the run_id of a previous run whose checkpoints are
        used to resume execution. When ``None`` (default), a fresh
        simulation is executed via the legacy ``Simulation`` shim.
    """
    if resume is not None:
        return _run_resume(Path(config_path), resume)

    from hydromodpy.project import Simulation

    with Simulation(config_path) as project:
        result = project.run()
        return {
            "name": result.name,
            "sim_id": result.sim_id,
        }


def _run_resume(config_path: Path, run_id: str) -> dict:
    """Resume a previously interrupted simulation via the new Pipeline."""
    from hydromodpy.pipeline import Pipeline, PipelineState
    from hydromodpy.pipeline.checkpoint import CheckpointStore
    from hydromodpy.pipeline.ledger import StepsLedger
    from hydromodpy.pipeline.steps import standard_steps

    workspace = _resolve_workspace(config_path)
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


def _resolve_workspace(config_path: Path) -> Path:
    """Walk up from ``config_path`` to find a workspace root."""
    for parent in [config_path.parent, *config_path.parents]:
        if (parent / "hydromodpy.duckdb").exists() or (
            parent / ".hmp"
        ).is_dir():
            return parent
    return config_path.parent
