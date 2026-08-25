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
   trials through :mod:`hydromodpy.calibration.optim.promotion`.

The ``objective`` argument is a Python escape hatch
(``"module.path:fn"``) for users who need a custom scalar -- the TOML
``[calibration].objective`` + ``[calibration].variable`` pair already
covers the standard NSE / KGE / RMSE cases.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.calibration.config import CalibrationConfig, scoring_window_bounds
from hydromodpy.calibration.metrics import build_metric_extractor
from hydromodpy.calibration.optim.cache import ParamsHashCache
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.optim.progress_reporter import ConsoleProgressReporter
from hydromodpy.calibration.optim.promotion import promote_iterations
from hydromodpy.calibration.runners.sandbox import keep_trial_scratch
from hydromodpy.calibration.runners.state import (
    CalibrationStoreFactory,
    SessionChain,
    build_cache_context,
    default_store_factory,
    load_metric_fn_entry_point,
    preload_hash_cache,
    space_from_config,
)
from hydromodpy.calibration.runners.state import (
    override_paths as resolve_override_paths,
)
from hydromodpy.calibration.runners.trial import (
    TrialMetricFn,
    prepare_trials,
)
from hydromodpy.core.exceptions import ObjectiveError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.calibration.optim.engine import CalibrationSession
    from hydromodpy.calibration.optim.parameters import ParameterSpace
    from hydromodpy.calibration.report import CalibrationReport
    from hydromodpy.calibration.runners.trial import TrialContext

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# TOML loader
# ---------------------------------------------------------------------------


def load_toml_calibration(path: Path) -> tuple[CalibrationConfig, dict]:
    """Return the validated ``[calibration]`` section of ``path`` and the raw TOML.

    Read through ``base_config`` resolution, the same way the pipeline reads the
    file. Reading it raw instead made a ``[calibration]`` section inherited from
    a base configuration invisible here while the pipeline resolved it, so a
    calibration overlay of two lines failed on "No [calibration] section".
    """
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    raw = load_toml_with_base_config(path)
    if "calibration" not in raw:
        raise ValueError(f"No [calibration] section in {path}")
    cfg = CalibrationConfig.model_validate(raw["calibration"])
    _resolve_stream_geometry_paths(cfg, path)
    return cfg, raw


def _resolve_stream_geometry_paths(cfg: CalibrationConfig, config_path: Path) -> None:
    """Anchor every relative ``stream_geometry_path`` to the file that declares it.

    A path in a TOML is relative to that TOML, the way ``base_config`` is, and a
    bare filename falls back to ``<project>/data/hydrography/`` like every other
    data path. Reading it against the working directory instead made the run
    depend on where it was launched from.

    Called from :func:`run_calibration_core`, where the CLI, the staged and the
    programmatic routes converge, and again from :func:`load_toml_calibration`
    for the readers that never run a calibration. Running twice is harmless: the
    second pass sees absolute paths and skips them.

    A path that resolves to nothing is left exactly as declared. Loading a
    configuration must not require its data to be present: ``--list-phases`` has
    to work on a machine that holds none of it, and the criterion already names
    the file it could not read.
    """
    base = config_path.expanduser().resolve().parent
    for output in cfg.outputs.values():
        declared = getattr(output, "stream_geometry_path", None)
        if not declared or Path(declared).is_absolute():
            continue
        candidate = Path(declared)
        found = next(
            (
                trial
                for root in (base, base.parent, base.parent.parent)
                for trial in (root / candidate, root / "data" / "hydrography" / candidate.name)
                if trial.exists()
            ),
            None,
        )
        if found is not None:
            output.stream_geometry_path = str(found.resolve())


def _api_isolation_needed(parallel: int) -> bool:
    """Whether api solves must be isolated in a child process this session.

    True for any PARALLEL session. The decision is on parallelism alone, NOT the
    declared ``mf6_runner``: the effective runner is resolved at build time and an
    exposed-band (marnage) coupling forces the ``api`` runner even when the config
    leaves ``mf6_runner`` at its ``subprocess`` default. ``_run_via_api`` is
    reached ONLY for that effective api runner, so isolating whenever trials run
    concurrently is correct (and a no-op for subprocess solves, which never reach
    it). A serial session keeps the in-process api path (live progress bar, no
    spawn). Isolating gives each concurrent libmf6 its own process, so the global
    Fortran INPUT state never collides across threads.
    """
    return parallel > 1


def _assert_bounds_valid(trial_ctx: Any, space: ParameterSpace) -> None:
    """Reject calibration bounds that fall outside the target field's valid range.

    Field validation (e.g. a specific yield must stay in its physical range)
    only fires when the process is built, not on plain attribute assignment, so
    a bad bound is silent until each trial that samples there crashes at fork.
    This probe injects every parameter's lower and upper bound into a copy of the
    config and rebuilds the flow once; a build failure means the bound is out of
    range, so fail fast with a clear message instead of losing trials.

    Only flow-targeted parameters are probed (the common case: K, Sy, Ss,
    bedleak, ...). A base flow that already fails to build is left for the run to
    surface, so a pre-existing config issue is never blamed on a bound.
    """
    from hydromodpy.calibration.optim.parameters import apply_parameter_to_config
    from hydromodpy.physics.flow import Flow

    base_cfg = getattr(trial_ctx, "base_cfg", None) or getattr(
        getattr(trial_ctx, "ctx", None), "cfg", None
    )
    if base_cfg is None or not hasattr(base_cfg, "model_copy"):
        return
    try:
        Flow(config=base_cfg.flow)
    except Exception:
        return
    for param in space:
        if param.effective_path is None or not param.effective_path.startswith("flow."):
            continue
        for label, value in (("lower", param.lower), ("upper", param.upper)):
            probe = base_cfg.model_copy(deep=True)
            apply_parameter_to_config(probe, param, float(value))
            try:
                Flow(config=probe.flow)
            except Exception as exc:
                lines = [ln.strip() for ln in str(exc).splitlines() if ln.strip()]
                detail = next(
                    (ln for ln in lines if "outside" in ln.lower()),
                    lines[-1] if lines else str(exc),
                )
                raise ValueError(
                    f"calibration parameter {param.name!r} {label} bound {value:g} is outside "
                    f"the valid range for {param.effective_path!r}: {detail}"
                ) from exc


def _assert_network_conductance_proportional(cfg: CalibrationConfig, trial_ctx: Any) -> None:
    """Refuse a stream-network criterion whose drain conductance is fixed.

    The criterion calibrates the ratio K/R, and that only holds while the drain
    conductance follows the conductivity: ``C = K * cell_area / top_thickness``
    on both MODFLOW backends, ``C = K * cell_area`` on Boussinesq. All three
    apply it as a fallback, and only when the configured conductance is not
    strictly positive. A fixed value breaks the invariance from a factor 1.05
    onwards, and the run still completes and returns a number, so it has to be
    refused before the first solve.
    """
    network_outputs = sorted(
        name for name, output in cfg.outputs.items() if output.support == "network"
    )
    if not network_outputs:
        return
    flow = getattr(getattr(trial_ctx, "base_cfg", None), "flow", None)
    if flow is None or "drainage" not in flow.active_bc:
        return
    boundary = flow.bc.get("drainage")
    if boundary is None or boundary.value is None or float(boundary.value) <= 0.0:
        return
    names = ", ".join(repr(name) for name in network_outputs)
    raise ObjectiveError(
        f"Network calibration output(s) {names}: flow.bc.{boundary.kind}.drainage.value is "
        f"{float(boundary.value):g} {boundary.units}, a fixed drain conductance. The criterion "
        "calibrates the ratio K/R, which holds only while the conductance follows the "
        "conductivity (C = K * cell_area / top_thickness, the fallback applied when the "
        "configured value is not strictly positive). A fixed conductance leaves that "
        "invariance from a factor 1.05 onwards, so the calibrated ratio would mean nothing. "
        "Set the value to zero."
    )


def _search_space_payload(space: ParameterSpace) -> dict[str, Any]:
    """Return the searched bounds, one entry per parameter, as plain data.

    Written into the session journal so the frozen search space is readable
    next to the trials it produced, without opening the index.
    """
    return {
        param.name: {
            "bounds": [param.lower, param.upper],
            "transform": param.transform,
            "target": param.effective_path,
            "units": param.units,
        }
        for param in space
    }


def _persist_observed_for_report(catalog: Any, trial_ctx: Any, variable: str) -> None:
    """Store the calibration observations so the report can draw obs-vs-sim.

    The promoted run writes the simulated series to the catalog; the matching
    observed series is sim-independent, so it lands once in the ``observations``
    table keyed by station. Only the lake-level family is wired today; the
    observed station is prefixed ``lake:<id>`` to line up with the simulated
    LAK stage station.
    """
    if variable != "lake_level":
        return
    ctx = getattr(trial_ctx, "ctx", None)
    write = getattr(catalog, "write_observations", None)
    if ctx is None or write is None:
        return
    from hydromodpy.calibration.metrics.series import load_observed

    for obs in load_observed(ctx, "lake_level"):
        station = obs.station_id if obs.station_id.startswith("lake:") else f"lake:{obs.station_id}"
        try:
            write(station, "lake_level", obs.series, unit="m", quality="observed")
        except Exception as exc:
            logger.warning("Could not persist observed lake level %s for report: %s", station, exc)


# ---------------------------------------------------------------------------
# Core loop (caller-agnostic)
# ---------------------------------------------------------------------------


def _release_session_scratch(trial_ctx: TrialContext) -> None:
    """Drop the preprocessing tree the session shared across its trials.

    Trials skip the setup steps and read the tree built once for the session,
    so no trial may delete it; and only a *promoted* run reaches the export
    step that normally does. A session that promotes nothing therefore used to
    leave hundreds of MB of DEM and flow rasters under ``.hmp/scratch``. This
    runs on every exit path (success, failure, SIGINT) and never raises.
    """
    from hydromodpy.spatial.geographic.store_ingestion import cleanup_stable_folder

    geographic = getattr(getattr(trial_ctx.ctx, "setup", None), "geographic", None)
    if geographic is None:
        return
    geographic_cfg = getattr(getattr(trial_ctx, "base_cfg", None), "geographic", None)
    keep = keep_trial_scratch() or bool(getattr(geographic_cfg, "write_intermediates", False))
    try:
        cleanup_stable_folder(geographic, keep=keep)
    except Exception:  # noqa: BLE001 - cleanup never decides the session outcome
        logger.warning("Could not remove the calibration session scratch", exc_info=True)


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
    chain: SessionChain | None = None,
) -> CalibrationReport:
    """Heart of the calibration loop. Caller-agnostic.

    The caller is responsible for:

    - building a :class:`TrialContext` (via :func:`prepare_trials` with the
      appropriate ``parameter_space`` and ``override_paths``),
    - resolving the workspace,
    - building the :class:`ParameterSpace`,
    - providing ``cfg_path`` when ``cfg.materialize_candidates`` is True
      (overlays are derived from the on-disk TOML).

    ``chain`` names the session and places it in a chain of phases. A
    standalone calibration leaves it unset and gets a fresh session id.

    ``cfg_path`` is also what a declared ``stream_geometry_path`` is anchored
    on. The three entry points converge here and all three pass it, whereas only
    the CLI one goes through :func:`load_toml_calibration`; anchoring anywhere
    else leaves the two programmatic routes reading the working directory.
    """
    from hydromodpy.calibration.persistence import CalibrationPersistence
    from hydromodpy.calibration.report import CalibrationReport

    if cfg_path is not None:
        _resolve_stream_geometry_paths(cfg, cfg_path)
    # Same refusal for a mono-phase run as for a staged one: an optimizer_kwarg
    # foreign to the declared method used to die as a bare TypeError inside the
    # adapter constructor, after the first solve.
    cfg.validate_registry()
    override_paths = resolve_override_paths(cfg)

    factory = store_factory or default_store_factory
    catalog = factory(workspace, cfg.persistence)
    persistence = CalibrationPersistence(
        catalog, persistence=cfg.persistence, project_root=workspace
    )

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
                warmup_periods=int(cfg.warmup_periods),
                scoring_window=scoring_window_bounds(cfg.scoring_window),
            )

    use_api_isolation = _api_isolation_needed(cfg.parallel)
    _assert_bounds_valid(trial_ctx, space)
    _assert_network_conductance_proportional(cfg, trial_ctx)

    session_id = chain.session_id if chain is not None else uuid.uuid4().hex
    persistence.start_session(
        session_id=session_id,
        project=project_label,
        method=cfg.method,
        objective_name=cfg.objective,
        search_space=_search_space_payload(space),
        config=cfg.model_dump(),
        parent_session_id=chain.parent_session_id if chain is not None else None,
        root_session_id=chain.root_session_id if chain is not None else None,
        phase_name=chain.phase_name if chain is not None else None,
        phase_index=chain.phase_index if chain is not None else None,
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
        from hydromodpy.calibration.runners.trial import run_trial_light

        result = run_trial_light(
            trial_ctx,
            sugg.values,
            objective=cfg.objective,
            variable=cfg.variable,
            metric_fn=metric_fn,
            trial_id=sugg.trial_id,
        )
        # calibration_iterations CHECK accepts only finite lifecycle states.
        # Map "failed" metric errors onto "crashed" for persistence.
        db_status = "crashed" if result.status == "failed" else result.status
        meta: dict[str, object] = {}
        if result.error:
            meta["error"] = result.error
            logger.warning("Calibration trial %d %s: %s", sugg.trial_id, db_status, result.error)
        if cfg.persist_iteration_detail == "full":
            meta["block_costs"] = dict(result.metrics) if result.metrics else {}
        if materialize_root is not None and cfg_path is not None:
            from hydromodpy.calibration.runners.materialize import materialize_candidate

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

    # An EvaluationResult carries no parameters, and a cache hit never reaches
    # the evaluator, so the suggestion is the only place the values of a trial
    # are seen. Keeping them is what lets the report name the best candidate.
    values_by_trial: dict[int, dict[str, float]] = {}

    def on_iteration(sugg: ParamSuggestion, result: EvaluationResult) -> None:
        values_by_trial[sugg.trial_id] = {k: float(v) for k, v in sugg.values.items()}
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
        from hydromodpy.solver.modflow6.run import api_isolation_context

        # Isolate each api solve in its own process for the PARALLEL trial loop
        # only; promotion below replays a single run and stays in-process.
        with api_isolation_context(use_api_isolation):
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
            if best_sim_id is not None:
                _persist_observed_for_report(catalog, trial_ctx, cfg.variable)

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
        _release_session_scratch(trial_ctx)
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
            best_sim_id=best_sim_id,
        )
        close = getattr(catalog, "close", None)
        if close is not None:
            close()

    return CalibrationReport(
        session_id=session_id,
        method=cfg.method,
        n_iterations=len(session.history),
        best_objective=best.objective_value if best else None,
        best_sim_id=best_sim_id,
        best_parameters=values_by_trial.get(best.trial_id) if best else None,
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
    cfg, _raw = load_toml_calibration(cfg_path)
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


__all__ = ["load_toml_calibration", "run_calibration_cli", "run_calibration_core"]
