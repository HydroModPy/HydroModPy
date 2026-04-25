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
from hydromodpy.simulation.execution.trial import (
    TrialMetricFn,
    prepare_trials,
    promote_trial,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TOML + ParameterSpace helpers
# ---------------------------------------------------------------------------


def _load_toml_calibration(path: Path) -> tuple[CalibrationConfig, dict]:
    from hydromodpy._cli.legacy_calibration import normalize_legacy_calibration_section

    with open(path, "rb") as f:
        raw = tomllib.load(f)
    raw = normalize_legacy_calibration_section(raw)
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
            "'flow.param.K.field_homogeneous.value') so values can be injected "
            "into the simulation config."
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
    from hydromodpy.results._db_retry import with_lock_retry

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
    from hydromodpy.results._db_retry import with_lock_retry

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


def _update_best_sim_id(catalog, session_id: str, sim_id: str) -> None:
    from hydromodpy.results._db_retry import with_lock_retry

    @with_lock_retry()
    def _run() -> None:
        sid = uuid.UUID(session_id) if len(session_id) == 32 else session_id
        sim_uuid = uuid.UUID(sim_id) if len(sim_id) == 32 else sim_id
        catalog.connection.execute(
            "UPDATE calibration_sessions SET best_sim_id = ? WHERE session_id = ?",
            [sim_uuid, sid],
        )

    _run()


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
    """
    cfg_path = Path(config_path).expanduser().resolve()
    cfg, _raw = _load_toml_calibration(cfg_path)
    space = _space_from_config(cfg)
    override_paths = _override_paths(cfg)

    # Prepare the pipeline once (steps [0..earliest) run here).
    trial_ctx = prepare_trials(
        cfg_path,
        override_paths=override_paths,
        parameter_space=space,
    )

    # Resolve workspace.
    if workspace is not None:
        ws_root = Path(workspace).expanduser().resolve()
    else:
        ws_root = trial_ctx.workspace

    from hydromodpy.calibration.persistence import CalibrationPersistence
    from hydromodpy.results.catalog import SimulationCatalog

    catalog = SimulationCatalog(ws_root)
    persistence = CalibrationPersistence(catalog)

    engine_cache: ParamsHashCache | None = None
    if cfg.use_cache:
        engine_cache = ParamsHashCache()
        try:
            n_preloaded = _preload_hash_cache(catalog.connection, engine_cache)
            if n_preloaded:
                logger.info("Preloaded %d params_hash entries from DuckDB", n_preloaded)
        except Exception:
            logger.debug("Cache preload skipped (fresh catalog or schema mismatch)")

    # Resolve the metric extractor.
    if metric_fn is None:
        if objective and ":" in objective:
            metric_fn = _load_metric_fn_entry_point(objective)
        else:
            metric_fn = build_metric_extractor(cfg.variable, cfg.objective, trial_ctx.ctx)

    # Start the session row.
    session_id = uuid.uuid4().hex
    persistence.start_session(
        session_id=session_id,
        project=project,
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

    def wrapped_evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        last_suggestion[sugg.trial_id] = sugg
        from hydromodpy.simulation.execution.trial import run_trial_light

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
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=None,
            objective_value=result.primary_metric,
            status=db_status,
            duration_s=result.duration_s,
            components=dict(result.metrics) if result.metrics else None,
            metadata={"error": result.error} if result.error else {},
        )

    def on_iteration(result: EvaluationResult) -> None:
        sugg = last_suggestion.get(result.trial_id)
        if sugg is None:
            return
        persistence.append_iteration(session_id, sugg, result)
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
    session = engine.run()
    elapsed = time.perf_counter() - t0

    best = session.best

    # ----- Promotion step -----------------------------------------------
    promotion_count = 0
    best_sim_id: str | None = None

    if cfg.save_runs != "none":
        if cfg.save_runs == "best_n":
            top = persistence.top_n(session_id, cfg.save_best_n)
        else:  # "all"
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
            if best_sim_id is None and best_obj is not None and row["objective_value"] == best_obj:
                best_sim_id = sim_id

    persistence.finalize_session(
        session_id,
        best=best,
        n_iterations=len(session.history),
        duration_s=session.duration_s if session.duration_s else elapsed,
    )
    # finalize_session sets best_sim_id from best.sim_id (None for trials),
    # so we overwrite afterwards with the promoted sim_id when available.
    if best_sim_id is not None:
        _update_best_sim_id(catalog, session_id, best_sim_id)

    from hydromodpy.calibration.report import CalibrationReport

    report = CalibrationReport(
        session_id=session_id,
        method=cfg.method,
        n_iterations=len(session.history),
        best_objective=best.objective_value if best else None,
        best_sim_id=best_sim_id,
        duration_s=float(session.duration_s if session.duration_s else elapsed),
        save_runs=cfg.save_runs,
        promoted=promotion_count,
        workspace=ws_root,
    )
    if return_report:
        return report
    return report.to_dict()


__all__ = ["run_calibration_cli"]
