"""Top-N promotion of calibration trials.

After the ask/tell loop converges, the runner promotes selected trials
(top-N or all completed) into full simulations. This module isolates that
post-loop logic so the runners only deal with control flow. The promoted
best run is returned to the runner, which records it when the session is
closed by :class:`~hydromodpy.calibration.persistence.CalibrationPersistence`.

The ``sim_id`` column of the iterations table is filled BEFORE the run
replays, not after it: the last step of a promoted run renders the figures
declared in ``[display].figures``, and the ones about the calibration gate on
the run being named in ``calibration_iterations``. Filling the column after
the pipeline returned made every session figure report itself unavailable for
a reason that stopped being true one instruction later. Each promotion
therefore reserves its run id, writes the link, and clears it again when the
run fails, so a link never names a run that does not exist.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.optimizer import EvaluationResult
from hydromodpy.calibration.runners.trial import promote_prepared_trial
from hydromodpy.core import progress
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.calibration.persistence import CalibrationPersistence
    from hydromodpy.calibration.runners.trial import TrialContext

logger = get_logger(__name__)

_TRIAL_SUFFIX = "_trial_{iteration:04d}"
"""Appended to the promoted name of a kept trial that is not the best one."""


def stored_parameter_value(raw: Any) -> float:
    """Return the physical candidate value from a persisted parameter payload."""
    if isinstance(raw, dict):
        for key in ("value", "candidate_value", "transformed_value"):
            if key in raw:
                return float(raw[key])
        raise KeyError("Persisted parameter payload has no value")
    return float(raw)


def update_iter_sim_id(catalog, session_id: str, iteration: int, sim_id: str | None) -> None:
    """Write the promoted ``sim_id`` into ``calibration_iterations``.

    ``None`` clears the link, which is what a promotion that failed after its
    id was reserved must leave behind.
    """
    from hydromodpy.core.io.db_retry import with_lock_retry

    @with_lock_retry()
    def _run() -> None:
        sid = uuid.UUID(session_id) if len(session_id) == 32 else session_id
        sim_uuid: uuid.UUID | str | None = None
        if sim_id is not None:
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


def promoted_run_name(trial_ctx: TrialContext, phase: str | None) -> str:
    """Return the name of the run a calibration promotes as its best.

    It is the ``[simulation]`` name of the file, followed by the phase for a
    calibration in several phases: ``<name>_<phase>``, or ``<name>`` for one
    phase. Two calibration files of one project carry two simulation names, so
    their promoted runs never collide; a file run again gets the ``.v2`` the
    catalog gives any run whose name is taken.
    """
    from hydromodpy.results.catalog.storage_paths import MAX_DIRNAME_LEN

    simulation = getattr(getattr(trial_ctx, "base_cfg", None), "simulation", None)
    base = getattr(simulation, "name", None) or Path(trial_ctx.cfg_path).stem
    name = f"{base}_{phase}" if phase else str(base)
    # Room for the longest suffix a promoted run can take, "_trial_0000.v99",
    # checked here, before the search, rather than after hours of trials.
    longest = len(name) + len(_TRIAL_SUFFIX.format(iteration=0)) + len(".v99")
    if longest > MAX_DIRNAME_LEN:
        raise CalibrationError(
            f"The promoted runs of this calibration would be named {name!r} plus a suffix, "
            f"{longest} characters where a run folder holds {MAX_DIRNAME_LEN}. Shorten the "
            "[simulation] name or the phase name."
        )
    return name


def registered_run_name(catalog: Any, sim_id: str | None) -> str | None:
    """Return the name the catalog registered a promoted run under.

    It can differ from the name asked for: a name already taken gets a
    ``.v2`` suffix. ``None`` when no run was promoted or the store keeps no
    simulation row.
    """
    if sim_id is None:
        return None
    from hydromodpy.core.io.db_retry import with_lock_retry

    @with_lock_retry()
    def _read() -> Any:
        return catalog.connection.execute(
            "SELECT name FROM simulations WHERE sim_id = ?",
            [uuid.UUID(str(sim_id))],
        ).fetchone()

    row = _read()
    return str(row[0]) if row and row[0] else None


def promote_iterations(
    *,
    cfg: CalibrationConfig,
    trial_ctx: TrialContext,
    catalog: Any,
    persistence: CalibrationPersistence,
    session_id: str,
    best: EvaluationResult | None,
    override_paths: dict[str, str],
    run_name: str,
) -> tuple[int, list[str], str | None]:
    """Promote selected trials and return ``(count, failures, best_sim_id)``.

    The best trial is promoted under ``run_name``. Any other trial that
    ``save_runs`` keeps gets ``<run_name>_trial_<iteration>``.
    """
    top = select_iterations_to_promote(cfg, persistence, session_id, best)
    if not top:
        return 0, [], None

    best_trial = best.trial_id if best is not None else int(top[0]["iteration"])
    failures: list[str] = []
    best_sim_id: str | None = None
    count = 0
    for row in progress.track(top, "Promoting calibrated runs"):
        promoted_as = (
            run_name
            if int(row["iteration"]) == best_trial
            else run_name + _TRIAL_SUFFIX.format(iteration=int(row["iteration"]))
        )
        logger.debug("Promoting %s", promoted_as)
        values = {
            name: stored_parameter_value(row["parameters"][name])
            for name in override_paths
            if name in row["parameters"]
        }
        sim_id = str(uuid.uuid4())
        # Linked first: the promoted run renders its figures as its own last
        # step, and the ones about the calibration read this link.
        update_iter_sim_id(catalog, session_id, row["iteration"], sim_id)
        try:
            with progress.suppressed():
                promote_prepared_trial(
                    trial_ctx,
                    values,
                    name=promoted_as,
                    session_id=session_id,
                    sim_id=sim_id,
                )
        except Exception as exc:
            update_iter_sim_id(catalog, session_id, row["iteration"], None)
            logger.exception("Promotion failed for iteration %d.", row["iteration"])
            failures.append(f"iteration {row['iteration']}: {exc}")
            continue
        count += 1
        if best is not None and int(row["iteration"]) == best.trial_id:
            best_sim_id = sim_id
    return count, failures, best_sim_id


__all__ = [
    "promoted_run_name",
    "registered_run_name",
    "stored_parameter_value",
    "update_iter_sim_id",
    "select_iterations_to_promote",
    "promote_iterations",
]
