"""Top-N promotion of calibration trials.

After the ask/tell loop converges, the runner promotes selected trials
(top-N or all completed) into full simulations and back-fills the
``sim_id`` column on the iterations table. This module isolates that
post-loop logic so the runners only deal with control flow.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optimizer import EvaluationResult
from hydromodpy.calibration.runners.trial import promote_prepared_trial
from hydromodpy.core import progress
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.calibration.persistence import CalibrationPersistence
    from hydromodpy.calibration.runners.trial import TrialContext

logger = get_logger(__name__)


def stored_parameter_value(raw: Any) -> float:
    """Return the physical candidate value from a persisted parameter payload."""
    if isinstance(raw, dict):
        for key in ("value", "candidate_value", "transformed_value"):
            if key in raw:
                return float(raw[key])
        raise KeyError("Persisted parameter payload has no value")
    return float(raw)


def update_iter_sim_id(catalog, session_id: str, iteration: int, sim_id: str) -> None:
    """Write the promoted ``sim_id`` into ``calibration_iterations``."""
    from hydromodpy.core.io.db_retry import with_lock_retry

    @with_lock_retry()
    def _run() -> None:
        sid = uuid.UUID(session_id) if len(session_id) == 32 else session_id
        sim_uuid = uuid.UUID(sim_id) if len(sim_id) == 32 else sim_id
        catalog.connection.execute(
            """
            UPDATE calibration_iterations
               SET sim_id = ?
             WHERE session_id = ? AND iteration = ?
            """,
            [sim_uuid, sid, int(iteration)],
        )

    _run()


def update_best_sim_id(catalog, session_id: str, sim_id: str) -> None:
    """Set ``best_sim_id`` on a finalized calibration session."""
    from hydromodpy.core.io.db_retry import with_lock_retry

    @with_lock_retry()
    def _run() -> None:
        sid = uuid.UUID(session_id) if len(session_id) == 32 else session_id
        sim_uuid = uuid.UUID(sim_id) if len(sim_id) == 32 else sim_id
        catalog.connection.execute(
            "UPDATE calibration_sessions SET best_sim_id = ? WHERE session_id = ?",
            [sim_uuid, sid],
        )

    _run()


def select_iterations_to_promote(
    cfg: CalibrationConfig,
    persistence: CalibrationPersistence,
    session_id: str,
    best: EvaluationResult | None,
) -> list[dict[str, Any]]:
    """Return the list of iteration rows to promote based on ``cfg.save_runs``."""
    if cfg.save_runs == "best_n":
        top = persistence.top_n(session_id, cfg.save_best_n)
    elif cfg.save_runs == "all":
        top = [
            row
            for row in persistence.load_iterations(session_id)
            if row["status"] == "completed" and row["objective_value"] is not None
        ]
    else:
        top = []
    if cfg.rerun_best_with_outputs and best is not None:
        completed = [
            row
            for row in persistence.load_iterations(session_id)
            if row["status"] == "completed" and row["objective_value"] is not None
        ]
        best_rows = [row for row in completed if int(row["iteration"]) == best.trial_id]
        if best_rows and all(int(row["iteration"]) != best.trial_id for row in top):
            top.append(best_rows[0])
    return top


def promote_iterations(
    *,
    cfg: CalibrationConfig,
    trial_ctx: TrialContext,
    catalog: Any,
    persistence: CalibrationPersistence,
    session_id: str,
    best: EvaluationResult | None,
    override_paths: dict[str, str],
) -> tuple[int, list[str], str | None]:
    """Promote selected trials and return ``(count, failures, best_sim_id)``."""
    top = select_iterations_to_promote(cfg, persistence, session_id, best)
    if not top:
        return 0, [], None

    failures: list[str] = []
    best_sim_id: str | None = None
    count = 0
    for row in progress.track(top, "Promoting calibrated runs"):
        run_name = f"{cfg.method}_iter_{row['iteration']:04d}"
        logger.debug("Promoting %s", run_name)
        values = {
            name: stored_parameter_value(row["parameters"][name])
            for name in override_paths
            if name in row["parameters"]
        }
        try:
            with progress.suppressed():
                sim_id = promote_prepared_trial(
                    trial_ctx,
                    values,
                    name=run_name,
                    session_id=session_id,
                )
        except Exception as exc:
            logger.exception("Promotion failed for iteration %d.", row["iteration"])
            failures.append(f"iteration {row['iteration']}: {exc}")
            continue
        update_iter_sim_id(catalog, session_id, row["iteration"], sim_id)
        count += 1
        if best is not None and int(row["iteration"]) == best.trial_id:
            best_sim_id = sim_id
    return count, failures, best_sim_id


__all__ = [
    "stored_parameter_value",
    "update_iter_sim_id",
    "update_best_sim_id",
    "select_iterations_to_promote",
    "promote_iterations",
]
