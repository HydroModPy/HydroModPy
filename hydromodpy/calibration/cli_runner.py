"""CLI entry point ``hmp calibrate <calibration.toml>``.

Workflow:

1. Load the TOML and validate the ``[calibration]`` section into a
   :class:`CalibrationConfig`.
2. Prepare the downstream pipeline once via :func:`prepare_trials`,
   reusing the earliest-affected-step optimisation so setup phases do
   not re-run per trial.
3. Drive the ask/tell loop through :class:`CalibrationEngine`, where
   each evaluation forks the prepared context, runs the solver in
   lightweight mode, and extracts the objective in RAM via
   :func:`hydromodpy.calibration.metrics.build_metric_extractor`.
4. Persist every iteration into the DuckDB ``calibration_iterations``
   table (``sim_id`` left ``NULL`` by default).
5. Honor ``save_runs`` -- ``"best_n"`` / ``"all"`` promote the chosen
   trials through :mod:`hydromodpy.calibration.promotion`.

The ``objective`` argument is a Python escape hatch
(``"module.path:fn"``) for users who need a custom scalar -- the TOML
``[calibration].objective`` + ``[calibration].variable`` pair already
covers the standard NSE / KGE / RMSE cases.
"""

from __future__ import annotations

import time
import tomllib
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.calibration.cache import ParamsHashCache
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.engine import CalibrationEngine
from hydromodpy.calibration.metrics import build_metric_extractor
from hydromodpy.calibration.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.progress_reporter import ConsoleProgressReporter
from hydromodpy.calibration.promotion import (
    promote_iterations,
    update_best_sim_id,
)
from hydromodpy.calibration.runners.trial import (
    TrialMetricFn,
    prepare_trials,
)
from hydromodpy.calibration.state import (
    CalibrationStoreFactory,
    build_cache_context,
    default_store_factory,
    load_metric_fn_entry_point,
    preload_hash_cache,
    space_from_config,
)
from hydromodpy.calibration.state import (
    override_paths as resolve_override_paths,
)
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.calibration.engine import CalibrationSession
    from hydromodpy.calibration.parameters import ParameterSpace
    from hydromodpy.calibration.report import CalibrationReport
    from hydromodpy.calibration.runners.trial import TrialContext

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# TOML loader
# ---------------------------------------------------------------------------


def _load_toml_calibration(path: Path) -> tuple[CalibrationConfig, dict]:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    if "calibration" not in raw:
        raise ValueError(f"No [calibration] section in {path}")
    return CalibrationConfig.model_validate(raw["calibration"]), raw


# ---------------------------------------------------------------------------
# Core loop (caller-agnostic)
# ---------------------------------------------------------------------------


def run_calibration_core(
    cfg: CalibrationConfig,
    trial_ctx: TrialContext,
    *,
    workspace: Path,
    space: ParameterSpace,
    project_label: str = "calibration",
    cfg_path: Path | None = None,
    metric_fn: TrialMetricFn | None = None,
    objective: str | None = None,
    store_factory: CalibrationStoreFactory | None = None,
) -> CalibrationReport:
    """Heart of the calibration loop. Caller-agnostic.

    The caller is responsible for:

    - building a :class:`TrialContext` (via :func:`prepare_trials` with the
      appropriate ``parameter_space`` and ``override_paths``),
    - resolving the workspace,
    - building the :class:`ParameterSpace`,
    - providing ``cfg_path`` when ``cfg.materialize_candidates`` is True
      (overlays are derived from the on-disk TOML).
    """
    from hydromodpy.calibration.persistence import CalibrationPersistence
    from hydromodpy.calibration.report import CalibrationReport

    override_paths = resolve_override_paths(cfg)

    factory = store_factory or default_store_factory
    catalog = factory(workspace, cfg.persistence)
    persistence = CalibrationPersistence(catalog, persistence=cfg.persistence)

    engine_cache: ParamsHashCache | None = None
    if cfg.use_cache:
        engine_cache = ParamsHashCache()
        try:
            n_preloaded = preload_hash_cache(catalog.connection, engine_cache)
            if n_preloaded:
                logger.info("Preloaded %d params_hash entries from DuckDB", n_preloaded)
        except Exception:
            logger.debug("Cache preload skipped (fresh catalog or schema mismatch)")

    if metric_fn is None:
        if objective and ":" in objective:
            metric_fn = load_metric_fn_entry_point(objective)
        else:
            metric_fn = build_metric_extractor(
                cfg.variable,
                cfg.objective,
                trial_ctx.ctx,
                outputs=cfg.outputs or None,
                objective_blocks=cfg.objective_blocks or None,
            )

    session_id = uuid.uuid4().hex
    persistence.start_session(
        session_id=session_id,
        project=project_label,
        method=cfg.method,
        objective_name=cfg.objective,
        config=cfg.model_dump(),
    )

    optimizer = build_optimizer(
        cfg.method,
        space,
        seed=cfg.seed,
        **cfg.optimizer_kwargs,
    )
    cache_context = build_cache_context(
        cfg=cfg,
        trial_ctx=trial_ctx,
        space=space,
        override_paths=override_paths,
        objective_entrypoint=objective,
    )

    last_suggestion: dict[int, ParamSuggestion] = {}

    materialize_root: Path | None = None
    if cfg.materialize_candidates:
        if cfg.candidates_root is None:
            raise ValueError(
                "calibration.materialize_candidates is True but "
                "calibration.candidates_root is not set."
            )
        if cfg_path is None:
            raise ValueError(
                "calibration.materialize_candidates is True but no source TOML "
                "is available. Provide cfg_path or run from a TOML-loaded Project."
            )
        materialize_root = Path(cfg.candidates_root).expanduser().resolve()
        materialize_root.mkdir(parents=True, exist_ok=True)

    def wrapped_evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        last_suggestion[sugg.trial_id] = sugg
        from hydromodpy.calibration.runners.trial import run_trial_light

        result = run_trial_light(
            trial_ctx,
            sugg.values,
            objective=cfg.objective,
            variable=cfg.variable,
            metric_fn=metric_fn,
        )
        # calibration_iterations CHECK accepts only finite lifecycle states.
        # Map "failed" metric errors onto "crashed" for persistence.
        db_status = "crashed" if result.status == "failed" else result.status
        meta: dict[str, object] = {}
        if result.error:
            meta["error"] = result.error
        if cfg.persist_iteration_detail == "full":
            meta["block_costs"] = dict(result.metrics) if result.metrics else {}
        if materialize_root is not None and cfg_path is not None:
            from hydromodpy.calibration.materialize import materialize_candidate

            try:
                overlay_path = materialize_candidate(
                    cfg_path,
                    dict(sugg.values),
                    space,
                    materialize_root,
                    iteration_index=sugg.trial_id,
                )
                meta["materialized_overlay"] = str(overlay_path)
            except Exception as exc:
                logger.warning(
                    "Failed to materialize overlay for trial %d: %s",
                    sugg.trial_id,
                    exc,
                )
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=None,
            objective_value=result.primary_metric,
            status=db_status,
            duration_s=result.duration_s,
            components=dict(result.metrics) if result.metrics else None,
            metadata=meta,
        )

    def on_iteration(result: EvaluationResult) -> None:
        sugg = last_suggestion.get(result.trial_id)
        if sugg is None:
            return
        persistence.append_iteration(
            session_id,
            sugg,
            result,
            detail=cfg.persist_iteration_detail,
        )

    logger.info(
        "Calibration session %s | method=%s max_iter=%d save_runs=%s",
        session_id,
        cfg.method,
        cfg.max_iter,
        cfg.save_runs,
    )

    engine = CalibrationEngine(
        space=space,
        optimizer=optimizer,
        evaluator=wrapped_evaluator,
        max_iter=cfg.max_iter,
        batch_size=cfg.batch_size,
        parallel=cfg.parallel,
        cache=engine_cache,
        cache_context=cache_context,
        progress=ConsoleProgressReporter(cfg.method, cfg.max_iter),
        session_id=session_id,
        on_iteration=on_iteration,
    )

    t0 = time.perf_counter()
    session: CalibrationSession | None = None
    final_status = "failed"
    final_error: str | None = None
    promotion_count = 0
    promotion_failures: list[str] = []
    best_sim_id: str | None = None
    best: EvaluationResult | None = None

    try:
        session = engine.run()
        best = session.best

        promotion_required = cfg.save_runs != "none" or cfg.rerun_best_with_outputs
        if promotion_required:
            if cfg_path is None:
                raise ValueError(
                    "Calibration promotion requires a source TOML "
                    "(promotion replays the full pipeline). Provide cfg_path or disable "
                    "save_runs/rerun_best_with_outputs."
                )
            promotion_count, promotion_failures, best_sim_id = promote_iterations(
                cfg=cfg,
                trial_ctx=trial_ctx,
                catalog=catalog,
                persistence=persistence,
                session_id=session_id,
                best=best,
                override_paths=override_paths,
            )

        n_total = len(session.history)
        n_ok = sum(1 for h in session.history if h.status in ("completed", "cached"))
        if n_total > 0 and n_ok == n_total:
            final_status = "completed"
        elif n_ok > 0:
            final_status = "partial"
        else:
            final_status = "failed"
            if n_total == 0:
                final_error = "no iterations completed"
        if promotion_failures:
            final_status = "partial" if promotion_count > 0 else "failed"
            final_error = "; ".join(promotion_failures)
    except KeyboardInterrupt:
        final_status = "aborted"
        final_error = "SIGINT"
        raise
    except Exception as exc:
        final_status = "failed"
        final_error = str(exc)
        raise
    finally:
        elapsed = time.perf_counter() - t0
        n_iter = len(session.history) if session is not None else 0
        duration = session.duration_s if session is not None and session.duration_s else elapsed
        persistence.finalize_session(
            session_id,
            best=best,
            n_iterations=n_iter,
            duration_s=duration,
            status=final_status,
            error=final_error,
        )
        if best_sim_id is not None:
            update_best_sim_id(catalog, session_id, best_sim_id)
        close = getattr(catalog, "close", None)
        if close is not None:
            close()

    return CalibrationReport(
        session_id=session_id,
        method=cfg.method,
        n_iterations=len(session.history),
        best_objective=best.objective_value if best else None,
        best_sim_id=best_sim_id,
        duration_s=float(session.duration_s if session.duration_s else elapsed),
        save_runs=cfg.save_runs,
        promoted=promotion_count,
        workspace=workspace,
        store_factory=lambda path: factory(path, cfg.persistence),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_calibration_cli(
    config_path: Path | str,
    *,
    objective: str | None = None,
    workspace: Path | str | None = None,
    project: str = "calibration",
    metric_fn: TrialMetricFn | None = None,
    return_report: bool = False,
    store_factory: CalibrationStoreFactory | None = None,
) -> dict | object:
    """Run a calibration described by ``config_path``.

    Parameters
    ----------
    config_path
        Path to a TOML that declares ``[calibration]`` plus the full
        ``[simulation]`` / ``[flow]`` / ``[data]`` blocks.
    objective
        Optional escape hatch: ``"module.path:callable"`` selects the
        RAM metric extractor. Takes precedence over ``metric_fn``.
    workspace
        Override the project catalog root (defaults to the one resolved
        from the TOML).
    project
        Project label written to ``calibration_sessions.project``.
    metric_fn
        Programmatic override for the metric extractor.
    return_report
        When True, return the structured :class:`CalibrationReport`
        instead of its ``to_dict()`` payload.
    """
    cfg_path = Path(config_path).expanduser().resolve()
    cfg, _raw = _load_toml_calibration(cfg_path)
    space = space_from_config(cfg)
    paths = resolve_override_paths(cfg)

    trial_ctx = prepare_trials(
        cfg_path,
        override_paths=paths,
        parameter_space=space,
    )

    if workspace is not None:
        ws_root = Path(workspace).expanduser().resolve()
    else:
        ws_root = trial_ctx.workspace

    report = run_calibration_core(
        cfg,
        trial_ctx,
        workspace=ws_root,
        space=space,
        project_label=project,
        cfg_path=cfg_path,
        metric_fn=metric_fn,
        objective=objective,
        store_factory=store_factory,
    )
    if return_report:
        return report
    return report.to_dict()


__all__ = ["run_calibration_cli", "run_calibration_core"]
