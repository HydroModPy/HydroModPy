"""CLI entry point for ``hmp run <calibration.toml>``.

Workflow:

1. Load the TOML and validate the ``[calibration]`` section into a
   :class:`CalibrationConfig`.
2. Prepare the downstream pipeline **once** via :func:`prepare_trials`,
   reusing the earliest-affected-step optimisation so the setup phases
   (geographic, mesh, data loading) do not re-run per trial.
3. Drive the ask/tell loop through :class:`CalibrationEngine`, where
   each evaluation forks the prepared context, runs the solver in
   lightweight mode, and extracts the objective in RAM via
   :func:`hydromodpy.calibration.metrics.build_metric_extractor`.
4. Persist every iteration into the DuckDB ``calibration_iterations``
   table (``sim_id`` left ``NULL`` by default).
5. Honor ``save_runs`` - ``"best_n"`` / ``"all"`` replay the chosen
   trials through :func:`promote_trial` and back-fill ``sim_id`` in the
   iterations table. ``"none"`` (the default) leaves the trace-only.

The ``objective`` argument is a Python escape hatch
(``"module.path:fn"``) for users who need a custom scalar - the TOML
``[calibration].objective`` + ``[calibration].variable`` pair already
covers the standard NSE / KGE / RMSE cases.
"""

from __future__ import annotations

import importlib
import logging
import sys
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
from hydromodpy.calibration.parameters import ParameterSpace
from hydromodpy.calibration.runners.trial import (
    TrialMetricFn,
    prepare_trials,
    promote_trial,
)

if TYPE_CHECKING:
    from hydromodpy.calibration.engine import CalibrationSession
    from hydromodpy.calibration.report import CalibrationReport
    from hydromodpy.calibration.runners.trial import TrialContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TOML + ParameterSpace helpers
# ---------------------------------------------------------------------------


def _load_toml_calibration(path: Path) -> tuple[CalibrationConfig, dict]:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    if "calibration" not in raw:
        raise ValueError(f"No [calibration] section in {path}")
    return CalibrationConfig.model_validate(raw["calibration"]), raw


def _space_from_config(cfg: CalibrationConfig) -> ParameterSpace:
    declarations = {
        name: decl.model_dump(exclude_none=True, by_alias=True)
        for name, decl in cfg.parameters.items()
    }
    return ParameterSpace.from_toml_mapping(declarations)


def _override_paths(cfg: CalibrationConfig) -> dict[str, str]:
    """Return the ``{parameter_name: dotted_path}`` mapping for trial injection."""
    out: dict[str, str] = {}
    for name, decl in cfg.parameters.items():
        dotted = decl.target if decl.target is not None else decl.path
        if dotted:
            out[name] = dotted
    if not out:
        raise ValueError(
            "Calibration parameters must declare a 'path' or 'target' (e.g. "
            "'flow.param.K.value') so values can be injected into the "
            "simulation config."
        )
    return out


# ---------------------------------------------------------------------------
# Custom Python objective escape hatch
# ---------------------------------------------------------------------------


def _load_metric_fn_entry_point(spec: str) -> TrialMetricFn:
    """Import a callable from ``module.path:fn`` for the escape-hatch path.

    The callable must match the :data:`TrialMetricFn` signature:
    ``(ctx, *, objective, variable) -> (primary_metric, dict[str, float])``.
    """
    if ":" not in spec:
        raise ValueError(f"objective entry-point must be 'module.path:callable', got: {spec!r}")
    mod_path, func_name = spec.split(":", 1)
    mod = importlib.import_module(mod_path)
    fn = getattr(mod, func_name)
    return fn


# ---------------------------------------------------------------------------
# Cache preload
# ---------------------------------------------------------------------------


def _preload_hash_cache(catalog_conn, cache: ParamsHashCache) -> int:
    """Populate ``cache`` from previously-promoted calibration iterations.

    Wrapped by DuckDB's lock-retry decorator so concurrent `hmp` sessions
    on the same workspace do not surface ``IOException``.
    """
    from hydromodpy.core.io.db_retry import with_lock_retry

    @with_lock_retry()
    def _run() -> list[tuple[str, str]]:
        rows = catalog_conn.execute(
            """
            SELECT params_hash, sim_id
              FROM calibration_iterations
             WHERE params_hash IS NOT NULL
               AND sim_id      IS NOT NULL
               AND status      = 'completed'
            """
        ).fetchall()
        return rows

    rows = _run()
    n_before = len(cache)
    for params_hash, sim_id in rows:
        if params_hash and sim_id is not None:
            cache.put(str(params_hash), str(sim_id))
    return len(cache) - n_before


# ---------------------------------------------------------------------------
# Sim ID back-fill helper
# ---------------------------------------------------------------------------


def _update_iter_sim_id(catalog, session_id: str, iteration: int, sim_id: str) -> None:
    """Write the promoted ``sim_id`` into ``calibration_iterations``."""
    from hydromodpy.core.io.db_retry import with_lock_retry

    @with_lock_retry()
    def _run() -> None:
        sid = uuid.UUID(session_id) if len(session_id) == 32 else session_id
        sim_uuid = uuid.UUID(sim_id) if len(sim_id) == 32 else sim_id
        catalog._connection.execute(
            """
            UPDATE calibration_iterations
               SET sim_id = ?
             WHERE session_id = ? AND iteration = ?
            """,
            [sim_uuid, sid, int(iteration)],
        )

    _run()


def _update_best_sim_id(catalog, session_id: str, sim_id: str) -> None:
    from hydromodpy.core.io.db_retry import with_lock_retry

    @with_lock_retry()
    def _run() -> None:
        sid = uuid.UUID(session_id) if len(session_id) == 32 else session_id
        sim_uuid = uuid.UUID(sim_id) if len(sim_id) == 32 else sim_id
        catalog._connection.execute(
            "UPDATE calibration_sessions SET best_sim_id = ? WHERE session_id = ?",
            [sim_uuid, sid],
        )

    _run()


# ---------------------------------------------------------------------------
# Core loop (caller-agnostic)
# ---------------------------------------------------------------------------


def _run_calibration(
    cfg: CalibrationConfig,
    trial_ctx: TrialContext,
    *,
    workspace: Path,
    space: ParameterSpace,
    project_label: str = "calibration",
    cfg_path: Path | None = None,
    metric_fn: TrialMetricFn | None = None,
    objective: str | None = None,
) -> CalibrationReport:
    """Heart of the calibration loop. Caller-agnostic.

    The caller is responsible for:

    - building a :class:`TrialContext` (via :func:`prepare_trials` with the
      appropriate ``parameter_space`` and ``override_paths``),
    - resolving the workspace,
    - building the :class:`ParameterSpace`,
    - providing ``cfg_path`` when ``cfg.materialize_candidates`` is True
      (overlays are derived from the on-disk TOML).

    Parameters
    ----------
    cfg
        Validated calibration configuration.
    trial_ctx
        Prepared trial context used by every evaluation.
    workspace
        Workspace root where the catalog DB lives.
    space
        Parameter space the optimizer samples from.
    project_label
        Label written to ``calibration_sessions.project``.
    cfg_path
        Optional path to the source TOML. Required when
        ``cfg.materialize_candidates`` is True.
    metric_fn
        Optional RAM-only metric extractor. When ``None`` the default
        extractor is built from ``cfg.outputs`` + ``cfg.objective_blocks``.
    objective
        Optional ``"module.path:callable"`` escape hatch. Takes
        precedence over ``metric_fn``.
    """
    from hydromodpy.calibration.persistence import CalibrationPersistence
    from hydromodpy.calibration.report import CalibrationReport
    from hydromodpy.results.catalog import SimulationCatalog

    override_paths = _override_paths(cfg)

    catalog = SimulationCatalog(workspace)
    persistence = CalibrationPersistence(catalog)

    engine_cache: ParamsHashCache | None = None
    if cfg.use_cache:
        engine_cache = ParamsHashCache()
        try:
            n_preloaded = _preload_hash_cache(catalog._connection, engine_cache)
            if n_preloaded:
                logger.info("Preloaded %d params_hash entries from DuckDB", n_preloaded)
        except Exception:
            logger.debug("Cache preload skipped (fresh catalog or schema mismatch)")

    if metric_fn is None:
        if objective and ":" in objective:
            metric_fn = _load_metric_fn_entry_point(objective)
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
        # calibration_iterations CHECK accepts only
        # {completed, diverged, timeout, crashed, cached} - map "failed"
        # (setup/metric errors) onto "crashed" for persistence.
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
        obj = result.objective_value
        obj_str = f"{obj:.6g}" if obj == obj else "nan"  # NaN-safe format
        print(
            f"  iter {result.trial_id:>4d}  obj={obj_str:>10} status={result.status}",
            file=sys.stderr,
        )

    engine = CalibrationEngine(
        space=space,
        optimizer=optimizer,
        evaluator=wrapped_evaluator,
        max_iter=cfg.max_iter,
        batch_size=cfg.batch_size,
        cache=engine_cache,
        session_id=session_id,
        on_iteration=on_iteration,
    )

    print(
        f"Calibration session {session_id} | method={cfg.method} "
        f"max_iter={cfg.max_iter} save_runs={cfg.save_runs}",
        file=sys.stderr,
    )

    t0 = time.perf_counter()
    session: CalibrationSession | None = None
    final_status = "failed"
    final_error: str | None = None
    promotion_count = 0
    best_sim_id: str | None = None
    best: EvaluationResult | None = None

    try:
        session = engine.run()
        best = session.best

        if cfg.save_runs != "none":
            if cfg_path is None:
                raise ValueError(
                    f"calibration.save_runs={cfg.save_runs!r} requires a source TOML "
                    "(promotion replays the full pipeline). Provide cfg_path or set "
                    "save_runs='none' for trace-only sessions."
                )
            if cfg.save_runs == "best_n":
                top = persistence.top_n(session_id, cfg.save_best_n)
            else:
                top = [
                    row
                    for row in persistence.load_iterations(session_id)
                    if row["status"] == "completed" and row["objective_value"] is not None
                ]
            if top:
                print(
                    f"Promoting {len(top)} iteration(s) as full simulations...",
                    file=sys.stderr,
                )
            best_obj = best.objective_value if best else None
            for row in top:
                values = {
                    name: float(row["parameters"][name])
                    for name in override_paths
                    if name in row["parameters"]
                }
                try:
                    sim_id = promote_trial(
                        cfg_path,
                        values,
                        paths=override_paths,
                        name=f"{cfg.method}_iter_{row['iteration']:04d}",
                        session_id=session_id,
                    )
                except Exception:
                    logger.exception(
                        "Promotion failed for iteration %d; skipping.",
                        row["iteration"],
                    )
                    continue
                _update_iter_sim_id(catalog, session_id, row["iteration"], sim_id)
                promotion_count += 1
                if (
                    best_sim_id is None
                    and best_obj is not None
                    and row["objective_value"] == best_obj
                ):
                    best_sim_id = sim_id

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
            _update_best_sim_id(catalog, session_id, best_sim_id)

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
) -> dict | object:
    """Run a calibration described by ``config_path``.

    Parameters
    ----------
    config_path
        Path to a TOML that declares ``[calibration]`` plus the full
        ``[simulation]`` / ``[flow]`` / ``[data]`` blocks.
    objective
        Optional escape hatch: when set to ``"module.path:callable"`` the
        named function is used as the RAM metric extractor. Takes
        precedence over ``metric_fn``. Leave ``None`` to use the default
        extractor built from the TOML ``[calibration].objective`` +
        ``[calibration].variable`` pair.
    workspace
        Override the workspace root (defaults to the one resolved from
        the TOML).
    project
        Project label written to ``calibration_sessions.project``.
    metric_fn
        Programmatic override for the metric extractor.
        ``(ctx, *, objective, variable) -> (primary, {component: value})``.
    return_report
        When True, return the structured :class:`CalibrationReport`
        instead of its ``to_dict()`` payload. Defaults to False to
        preserve the legacy CLI signature.
    """
    cfg_path = Path(config_path).expanduser().resolve()
    cfg, _raw = _load_toml_calibration(cfg_path)
    space = _space_from_config(cfg)
    override_paths = _override_paths(cfg)

    trial_ctx = prepare_trials(
        cfg_path,
        override_paths=override_paths,
        parameter_space=space,
    )

    if workspace is not None:
        ws_root = Path(workspace).expanduser().resolve()
    else:
        ws_root = trial_ctx.workspace

    report = _run_calibration(
        cfg,
        trial_ctx,
        workspace=ws_root,
        space=space,
        project_label=project,
        cfg_path=cfg_path,
        metric_fn=metric_fn,
        objective=objective,
    )
    if return_report:
        return report
    return report.to_dict()


# ---------------------------------------------------------------------------
# Programmatic shell
# ---------------------------------------------------------------------------


def run_calibration_programmatic(
    cfg: CalibrationConfig,
    *,
    project,
    workspace: Path | str | None = None,
    project_label: str = "calibration",
    metric_fn: TrialMetricFn | None = None,
    objective: str | None = None,
    return_report: bool = True,
) -> CalibrationReport | dict:
    """Run calibration without a calibration TOML file.

    The :class:`hydromodpy.Project` instance carries the simulation
    config; ``cfg.parameters`` declares the calibratable knobs. The
    project's source TOML is reused as ``cfg_path`` for
    :func:`prepare_trials` and (when applicable) for the
    ``materialize_candidates`` and ``save_runs`` hooks. Pure in-memory
    Projects (no source TOML) are not yet supported in programmatic mode
    because both the trial pipeline and the promotion step expect a path.

    Parameters
    ----------
    cfg
        In-memory calibration configuration.
    project
        :class:`hydromodpy.Project` whose simulation TOML drives the
        trial loop.
    workspace
        Override the workspace root. Defaults to ``project.workspace``
        when available.
    project_label
        Label written to ``calibration_sessions.project``.
    metric_fn
        Optional RAM-only metric extractor.
    objective
        Optional ``"module.path:callable"`` escape hatch.
    return_report
        When True (the default), return the :class:`CalibrationReport`;
        otherwise return its ``to_dict()`` payload.
    """
    src_path = getattr(project, "_config_path", None)
    if src_path is None:
        raise ValueError(
            "run_calibration_programmatic requires a Project loaded from a "
            "TOML file (the source path is needed for prepare_trials and "
            "promotion). Build the Project from a path before calibrating."
        )
    cfg_path = Path(src_path).expanduser().resolve()

    declarations = {
        name: decl.model_dump(exclude_none=True, by_alias=True)
        for name, decl in cfg.parameters.items()
    }
    space = ParameterSpace.from_toml_mapping(declarations)
    override_paths = _override_paths(cfg)

    trial_ctx = prepare_trials(
        cfg_path,
        override_paths=override_paths,
        parameter_space=space,
    )

    if workspace is not None:
        ws_root = Path(workspace).expanduser().resolve()
    else:
        ws_obj = getattr(project, "_ctx", None)
        ws_setup = getattr(ws_obj, "setup", None) if ws_obj is not None else None
        ws_root_obj = getattr(ws_setup, "workspace", None) if ws_setup is not None else None
        if ws_root_obj is not None:
            ws_root = Path(ws_root_obj.root)
        else:
            ws_root = trial_ctx.workspace

    report = _run_calibration(
        cfg,
        trial_ctx,
        workspace=ws_root,
        space=space,
        project_label=project_label,
        cfg_path=cfg_path,
        metric_fn=metric_fn,
        objective=objective,
    )
    if return_report:
        return report
    return report.to_dict()


__all__ = ["run_calibration_cli", "run_calibration_programmatic", "_run_calibration"]
