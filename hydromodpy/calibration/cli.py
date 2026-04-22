"""Thin CLI shell for ``hmp calibrate config.toml``.

Reads the TOML, builds a CalibrationEngine, runs the ask/tell loop, persists
iterations into the workspace DuckDB, and optionally promotes the top-N
best iterations into full simulations.

For now the default evaluator is an *analytical mock*: the caller must
provide their own ``objective_fn`` in Python when running a real model. A
follow-up phase will wire this to the solver Pipeline.
"""

from __future__ import annotations

import importlib
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

from hydromodpy.calibration.cache import ParamsHashCache
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.engine import CalibrationEngine
from hydromodpy.calibration.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.parameters import ParameterSpace


def _load_toml_calibration(path: Path) -> tuple[CalibrationConfig, dict]:
    import tomllib

    with open(path, "rb") as f:
        raw = tomllib.load(f)
    if "calibration" not in raw:
        raise ValueError(f"No [calibration] section in {path}")
    return CalibrationConfig.model_validate(raw["calibration"]), raw


def _space_from_config(cfg: CalibrationConfig) -> ParameterSpace:
    declarations = {
        name: decl.model_dump(exclude_none=True) for name, decl in cfg.parameters.items()
    }
    return ParameterSpace.from_toml_mapping(declarations)


def _load_evaluator(objective_module: str) -> Callable[[ParamSuggestion], EvaluationResult]:
    """Load a Python callable ``path.to.module:func``.

    The callable must accept a ``ParamSuggestion`` and return an
    ``EvaluationResult``. This is the hook a user writes to plug their own
    simulation into the calibration loop.
    """
    if ":" not in objective_module:
        raise ValueError(
            f"objective entry-point must be 'module.path:callable', got: {objective_module!r}"
        )
    mod_path, func_name = objective_module.split(":", 1)
    mod = importlib.import_module(mod_path)
    fn = getattr(mod, func_name)
    return fn


def _default_evaluator(sugg: ParamSuggestion) -> EvaluationResult:
    """Trivial analytical objective for smoke tests.

    Minimum at values = midpoint of each bound.
    """
    total = 0.0
    for _, v in sugg.values.items():
        total += (v - 1.0) ** 2
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=None,
        objective_value=float(total),
        status="completed",
        duration_s=0.0,
    )


def run_calibration_cli(
    config_path: Path | str,
    *,
    objective: str | None = None,
    workspace: Path | str | None = None,
    project: str = "calibration",
) -> dict:
    """Entry point used by ``hmp calibrate``.

    Parameters
    ----------
    config_path
        Path to a TOML file containing a ``[calibration]`` section.
    objective
        Python entry-point ``module.path:callable`` that returns an
        EvaluationResult from a ParamSuggestion. When ``None`` a trivial
        analytical objective is used (useful for smoke-testing).
    workspace
        Override workspace directory (defaults to CWD).
    project
        Project label for the calibration_sessions row.
    """
    cfg_path = Path(config_path).expanduser().resolve()
    cfg, _raw = _load_toml_calibration(cfg_path)
    space = _space_from_config(cfg)

    if workspace:
        ws = Path(workspace).expanduser().resolve()
    else:
        from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig

        full_cfg = HydroModPyConfig.from_toml(cfg_path)
        ws = full_cfg.workspace.workspace_root
    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.calibration.persistence import CalibrationPersistence

    catalog = SimulationCatalog(ws)
    persistence = CalibrationPersistence(catalog)

    evaluator = _load_evaluator(objective) if objective else _default_evaluator

    optimizer = build_optimizer(
        cfg.method,
        space,
        seed=cfg.seed,
        **cfg.optimizer_kwargs,
    )

    session_id = uuid.uuid4().hex
    persistence.start_session(
        session_id=session_id,
        project=project,
        method=cfg.method,
        objective_name=cfg.objective,
        config=cfg.model_dump(),
    )

    engine_cache = ParamsHashCache() if cfg.use_cache else None

    last_suggestion: dict[int, ParamSuggestion] = {}

    def wrapped_evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        last_suggestion[sugg.trial_id] = sugg
        t0 = time.perf_counter()
        try:
            result = evaluator(sugg)
        except Exception as exc:  # pragma: no cover - user objective crash
            return EvaluationResult(
                trial_id=sugg.trial_id,
                sim_id=None,
                objective_value=float("inf"),
                status="crashed",
                duration_s=time.perf_counter() - t0,
                metadata={"error": str(exc)},
            )
        return result

    def on_iteration(result: EvaluationResult) -> None:
        sugg = last_suggestion.get(result.trial_id)
        if sugg is None:
            return
        persistence.append_iteration(session_id, sugg, result)
        print(
            f"  iter {result.trial_id:>4d}  obj={result.objective_value:.6g} "
            f"status={result.status}",
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
    session = engine.run()

    best = session.best
    persistence.finalize_session(
        session_id,
        best=best,
        n_iterations=len(session.history),
        duration_s=session.duration_s,
    )

    # save_runs promotion hook: "best_n" and "all" promotion is expected to
    # be handled by the evaluator itself (which decides whether to register
    # a full simulation). At the CLI level we log the best iterations.
    promotion_count = 0
    if cfg.save_runs == "best_n":
        top = persistence.top_n(session_id, cfg.save_best_n)
        print(f"Top {len(top)} iterations (by objective):", file=sys.stderr)
        for row in top:
            print(
                f"  iter={row['iteration']:>4d} obj={row['objective_value']:.6g} "
                f"sim_id={row['sim_id']}",
                file=sys.stderr,
            )
            promotion_count += 1 if row["sim_id"] else 0

    summary = {
        "session_id": session_id,
        "method": cfg.method,
        "n_iterations": len(session.history),
        "best_objective": best.objective_value if best else None,
        "best_sim_id": best.sim_id if best else None,
        "duration_s": round(session.duration_s, 3),
        "save_runs": cfg.save_runs,
        "promoted": promotion_count,
    }
    return summary


__all__ = ["run_calibration_cli"]
