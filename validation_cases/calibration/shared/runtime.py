"""Runtime helpers for calibration same-solver twin benchmarks."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from validation_cases.calibration.shared.definitions import (
    CalibrationMethodProfile,
    ObservationNoiseSpec,
    TwinCalibrationBenchmarkResult,
    TwinCalibrationCaseDefinition,
    TwinMethodBenchmarkResult,
    build_payload,
)
from validation_cases.shared.runtime import _dump_toml, resolve_validation_results_dir


def _write_toml(path: Path, payload: dict[str, Any]) -> None:
    """Write one TOML payload to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_toml(payload), encoding="utf-8", newline="\n")


def _short_digest(text: str, *, size: int = 8) -> str:
    """Return one short stable digest used to keep Windows paths compact."""
    return hashlib.sha1(str(text).encode("utf-8")).hexdigest()[: int(size)]


def _compact_method_code(method_name: str) -> str:
    """Return one short readable code for a calibration method."""
    mapping = {
        "grid": "gs",
        "random_search": "rs",
        "cma_es": "cma",
        "scipy_nelder_mead": "snm",
        "gp_mapping": "gpm",
        "da_mh_gp": "damh",
        "truth": "tr",
    }
    token = str(method_name).strip().lower()
    return mapping.get(token, token[:4] or "m")


def _compact_case_code(definition: TwinCalibrationCaseDefinition) -> str:
    """Return one short stable identifier for a benchmark case."""
    return f"ct_{_short_digest(definition.case_id, size=10)}"


def _compact_calibration_id(
    definition: TwinCalibrationCaseDefinition,
    method_name: str,
) -> str:
    """Return one short calibration id to avoid path-length failures on Windows."""
    method_token = _compact_method_code(method_name)
    method_suffix = _short_digest(method_name, size=6)
    return f"{_compact_case_code(definition)}_{method_token}_{method_suffix}"


def _resolve_twin_benchmark_root(
    definition: TwinCalibrationCaseDefinition,
) -> Path:
    """Resolve one compact deterministic output root for a twin benchmark."""
    return resolve_validation_results_dir(
        test_file="validation_calibration_twin.py",
        run_name=_compact_case_code(definition),
    )


def _remove_artifact_path(path: Path, *, removed: list[str]) -> None:
    """Remove one heavy artifact path when it exists."""
    try:
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(str(path))
        elif path.is_file():
            path.unlink()
            removed.append(str(path))
    except OSError:
        return


def _prune_benchmark_artifacts(
    *,
    benchmark_root: Path,
    retention: str,
) -> tuple[str, ...]:
    """Prune heavy benchmark artifacts according to the selected retention mode."""
    mode = str(retention).strip().lower() or "minimal"
    if mode == "full":
        return ()
    if mode != "minimal":
        raise ValueError(f"Unsupported calibration benchmark artifact_retention '{retention}'.")

    removed: list[str] = []
    for top_level_path in (
        benchmark_root / "simulations",
        benchmark_root / "exports",
        benchmark_root / "hydromodpy.duckdb",
        benchmark_root / "hydromodpy.duckdb.wal",
    ):
        _remove_artifact_path(top_level_path, removed=removed)

    data_root = benchmark_root / "data"
    for data_artifact in (
        data_root / "cache.duckdb",
        data_root / "cache.duckdb.wal",
    ):
        _remove_artifact_path(data_artifact, removed=removed)
    if data_root.is_dir() and not any(data_root.iterdir()):
        _remove_artifact_path(data_root, removed=removed)

    for project_name in ("project", "project_truth"):
        project_root = benchmark_root / project_name
        for project_artifact in (
            project_root / "results_simulations",
            project_root / "results_stable",
            project_root / "hydromodpy_debug.log",
            project_root / ".solver_scratch",
        ):
            _remove_artifact_path(project_artifact, removed=removed)
        calibration_roots = project_root / "calibrations"
        if calibration_roots.is_dir():
            for runtime_candidates in calibration_roots.glob("*/runtime_candidates"):
                _remove_artifact_path(runtime_candidates, removed=removed)
        if project_root.is_dir() and not any(project_root.iterdir()):
            _remove_artifact_path(project_root, removed=removed)
    return tuple(removed)


def _placeholder_observations(
    definition: TwinCalibrationCaseDefinition,
) -> dict[str, tuple[float, ...]]:
    """Return one minimal observed-value mapping accepted by config parsing."""
    return {str(name): (0.0,) for name in definition.output_names}


def _reference_objective_enabled(
    *,
    definition: TwinCalibrationCaseDefinition,
) -> bool:
    """Return True when one case should run a shared reference-objective scan."""
    sample_count = definition.reference_objective_sample_count
    return sample_count is not None and int(sample_count) > 0


def _reference_objective_path(benchmark_root: Path) -> Path:
    """Return the persisted non-regular reference-objective payload path."""
    return benchmark_root / "objective_reference_samples.json"


def _block_normalized_cost_mapping(evaluation: Any) -> dict[str, float]:
    """Extract normalized block costs from one composite objective evaluation."""
    costs: dict[str, float] = {}
    for block in tuple(getattr(evaluation, "blocks", ())):
        name = getattr(block, "name", None)
        normalized_cost = getattr(block, "normalized_cost", None)
        if name is None or normalized_cost is None:
            continue
        try:
            value = float(normalized_cost)
        except (TypeError, ValueError):
            continue
        costs[str(name)] = value
    return costs


def _latin_hypercube_nd(
    *,
    rng: np.random.Generator,
    n_points: int,
    lower: np.ndarray,
    upper: np.ndarray,
) -> np.ndarray:
    """Generate one deterministic Latin-hypercube sample in arbitrary dimension."""
    n_dim = int(lower.size)
    unit = np.empty((n_points, n_dim), dtype=float)
    for index in range(n_dim):
        base = (np.arange(n_points, dtype=float) + rng.random(n_points)) / n_points
        rng.shuffle(base)
        unit[:, index] = base
    return lower + unit * (upper - lower)


def _sobol_nd(
    *,
    seed: int,
    n_points: int,
    lower: np.ndarray,
    upper: np.ndarray,
) -> np.ndarray:
    """Generate one Sobol sample when SciPy is available, else Latin-hypercube."""
    try:
        from scipy.stats import qmc

        n_dim = int(lower.size)
        engine = qmc.Sobol(d=n_dim, scramble=True, seed=int(seed))
        n_power = int(math.ceil(math.log2(max(1, n_points))))
        unit = engine.random_base2(m=n_power)[:n_points]
        return qmc.scale(unit, lower, upper)
    except Exception:
        rng = np.random.default_rng(int(seed))
        return _latin_hypercube_nd(
            rng=rng,
            n_points=n_points,
            lower=lower,
            upper=upper,
        )


def _reference_objective_samples(
    *,
    definition: TwinCalibrationCaseDefinition,
) -> tuple[tuple[str, ...], np.ndarray]:
    """Return non-regular reference-objective samples in full parameter space."""
    parameter_names = tuple(str(name) for name in definition.truth_params.keys())
    lower = np.asarray(
        [float(definition.bounds[name][0]) for name in parameter_names],
        dtype=float,
    )
    upper = np.asarray(
        [float(definition.bounds[name][1]) for name in parameter_names],
        dtype=float,
    )
    n_points = int(definition.reference_objective_sample_count or 0)
    sampling = str(definition.reference_objective_sampling).strip().lower()
    if n_points <= 0:
        return parameter_names, np.empty((0, len(parameter_names)), dtype=float)
    if sampling == "latin_hypercube":
        rng = np.random.default_rng(int(definition.reference_objective_seed))
        points = _latin_hypercube_nd(
            rng=rng,
            n_points=n_points,
            lower=lower,
            upper=upper,
        )
    elif sampling == "random":
        rng = np.random.default_rng(int(definition.reference_objective_seed))
        unit = rng.random((n_points, len(parameter_names)), dtype=float)
        points = lower + unit * (upper - lower)
    elif sampling == "sobol":
        points = _sobol_nd(
            seed=int(definition.reference_objective_seed),
            n_points=n_points,
            lower=lower,
            upper=upper,
        )
    else:
        raise ValueError(
            f"Unsupported reference_objective_sampling '{definition.reference_objective_sampling}'."
        )
    return parameter_names, np.asarray(points, dtype=float)


def _apply_observation_noise(
    observations: dict[str, tuple[float, ...]],
    *,
    noise: ObservationNoiseSpec | None,
) -> dict[str, tuple[float, ...]]:
    """Apply one deterministic Gaussian perturbation to synthetic observations."""
    if noise is None:
        return {
            str(name): tuple(float(value) for value in values)
            for name, values in observations.items()
        }
    rng = np.random.default_rng(int(noise.seed))
    perturbed: dict[str, tuple[float, ...]] = {}
    for name, values in observations.items():
        arr = np.asarray(values, dtype=float).reshape(-1)
        abs_sigma = float(noise.absolute_sigma_by_output.get(str(name), 0.0))
        rel_sigma = float(noise.relative_sigma_by_output.get(str(name), 0.0))
        sigma = np.sqrt(abs_sigma**2 + (rel_sigma * np.abs(arr)) ** 2)
        if np.any(sigma > 0.0):
            arr = arr + rng.normal(loc=0.0, scale=sigma, size=arr.shape)
        perturbed[str(name)] = tuple(float(value) for value in arr)
    return perturbed


def _seeded_method_profile(
    profile: CalibrationMethodProfile,
    *,
    seed: int | None,
) -> CalibrationMethodProfile:
    """Clone one method profile with an overridden stochastic seed."""
    if seed is None:
        return profile
    kwargs = dict(profile.method_kwargs)
    kwargs[str(profile.seed_kwarg_name)] = int(seed)
    return CalibrationMethodProfile(
        name=profile.name,
        method_kwargs=kwargs,
        persist_model_distribution=profile.persist_model_distribution,
        repeat_seeds=(),
        seed_kwarg_name=profile.seed_kwarg_name,
        success_metric=profile.success_metric,
    )


def _apply_evaluation_budget(
    profile: CalibrationMethodProfile,
    *,
    n_parameters: int,
    evaluation_budget: int | None,
) -> CalibrationMethodProfile:
    """Adapt one method profile to an approximate common evaluation budget."""
    if evaluation_budget is None:
        return profile
    budget = int(evaluation_budget)
    if budget <= 0:
        raise ValueError("evaluation_budget must be > 0")

    kwargs = dict(profile.method_kwargs)
    method = str(profile.name).strip().lower()
    if method == "grid":
        points_per_dim = max(1, int(budget ** (1.0 / max(1, n_parameters))))
        kwargs["points_per_dim"] = int(points_per_dim)
    elif method == "random_search":
        kwargs["max_iter"] = int(budget)
    elif method == "cma_es":
        kwargs["max_evaluations"] = int(budget)
        if "popsize" in kwargs:
            kwargs["popsize"] = max(4, min(int(kwargs["popsize"]), int(budget)))
    elif method == "scipy_nelder_mead":
        kwargs["maxiter"] = int(budget)
        kwargs["maxfev"] = int(budget)
    elif method == "gp_mapping":
        batch_size = max(1, int(kwargs.get("batch_size", 1)))
        n_init_default = max(1, int(kwargs.get("n_init", batch_size)))
        n_init = min(n_init_default, budget)
        remaining = max(0, budget - n_init)
        kwargs["n_init"] = int(n_init)
        kwargs["n_refine"] = int(remaining // batch_size)
    elif method == "da_mh_gp":
        base_init = max(1, int(kwargs.get("n_init", max(1, budget // 5))))
        base_iter = max(1, int(kwargs.get("max_iter", max(1, budget))))
        scale = float(budget) / float(base_init + base_iter)
        kwargs["n_init"] = max(1, int(round(base_init * scale)))
        kwargs["max_iter"] = max(1, int(round(base_iter * scale)))
        burn_in = kwargs.get("burn_in")
        if burn_in is not None:
            kwargs["burn_in"] = min(int(burn_in), max(0, int(kwargs["max_iter"]) - 1))
        thin = max(1, int(kwargs.get("thin", 1)))
        retained_target = max(8, min(32, int(budget)))
        retained_count = max(
            0,
            (int(kwargs["max_iter"]) - int(kwargs.get("burn_in", 0)) + thin - 1) // thin,
        )
        if retained_count < retained_target:
            kwargs["max_iter"] = int(kwargs.get("burn_in", 0)) + thin * retained_target
    else:
        raise ValueError(f"Unsupported evaluation-budget adaptation for method '{profile.name}'.")

    return CalibrationMethodProfile(
        name=profile.name,
        method_kwargs=kwargs,
        persist_model_distribution=profile.persist_model_distribution,
        repeat_seeds=profile.repeat_seeds,
        seed_kwarg_name=profile.seed_kwarg_name,
        success_metric=profile.success_metric,
    )


def _iter_selected_method_runs(
    selected_profiles: tuple[CalibrationMethodProfile, ...],
):
    """Yield one concrete method execution per selected profile and seed repeat."""
    for profile in selected_profiles:
        seeds = tuple(int(value) for value in profile.repeat_seeds)
        if not seeds:
            yield {
                "profile": profile,
                "effective_profile": profile,
                "instance_name": profile.name,
                "repeat_index": 1,
                "seed": (
                    None
                    if profile.seed_kwarg_name not in profile.method_kwargs
                    else int(profile.method_kwargs[profile.seed_kwarg_name])
                ),
            }
            continue
        for repeat_index, seed in enumerate(seeds, start=1):
            yield {
                "profile": profile,
                "effective_profile": _seeded_method_profile(profile, seed=seed),
                "instance_name": f"{profile.name}_seed{int(seed):03d}",
                "repeat_index": int(repeat_index),
                "seed": int(seed),
            }


def _param_abs_error(
    *,
    truth_params: dict[str, float],
    params_best: dict[str, Any],
) -> dict[str, float]:
    """Return absolute parameter errors against the truth."""
    errors: dict[str, float] = {}
    for name, truth in truth_params.items():
        raw_value = params_best.get(name)
        if raw_value is None:
            errors[str(name)] = math.inf
            continue
        errors[str(name)] = abs(float(raw_value) - float(truth))
    return errors


def _distribution_truth_metrics(
    *,
    model_distribution_path: Path | None,
    truth_params: dict[str, float],
    abs_tolerances: dict[str, float],
) -> tuple[int, bool | None, dict[str, float]]:
    """Evaluate whether a persisted distribution covers the truth within tolerances."""
    if model_distribution_path is None or not model_distribution_path.is_file():
        return 0, None, {}
    payload = json.loads(model_distribution_path.read_text(encoding="utf-8"))
    samples = payload.get("samples", [])
    if not isinstance(samples, list):
        return 0, None, {}

    min_errors = {str(name): math.inf for name in truth_params}
    truth_in_distribution = False
    for sample in samples:
        params_named = sample.get("params_named", {})
        if not isinstance(params_named, dict):
            continue
        sample_ok = True
        for name, truth in truth_params.items():
            raw_value = params_named.get(name)
            if raw_value is None:
                sample_ok = False
                continue
            error = abs(float(raw_value) - float(truth))
            if error < min_errors[str(name)]:
                min_errors[str(name)] = float(error)
            if error > float(abs_tolerances[str(name)]):
                sample_ok = False
        if sample_ok:
            truth_in_distribution = True

    normalized_min_errors = {
        str(name): (None if not math.isfinite(value) else float(value))
        for name, value in min_errors.items()
    }
    return int(len(samples)), truth_in_distribution, normalized_min_errors


def _estimate_candidate_runtime_seconds(
    *,
    mean_candidate_total_time_seconds: float | None,
    candidate_run_count: int,
    n_evaluations: int,
) -> float | None:
    """Estimate aggregate candidate runtime from mean-per-candidate timings."""
    if mean_candidate_total_time_seconds is None:
        return None
    run_count = int(candidate_run_count)
    if run_count <= 0:
        run_count = int(n_evaluations)
    if run_count <= 0:
        return None
    return float(mean_candidate_total_time_seconds) * float(run_count)


def _algorithm_overhead_time_seconds(
    *,
    calibration_time_seconds: float | None,
    estimated_candidate_runtime_seconds: float | None,
) -> float | None:
    """Estimate method overhead not spent inside candidate runtime segments."""
    if calibration_time_seconds is None or estimated_candidate_runtime_seconds is None:
        return None
    raw = float(calibration_time_seconds) - float(estimated_candidate_runtime_seconds)
    if raw < 0.0 and abs(raw) < 1.0e-9:
        return 0.0
    return max(0.0, raw)


def extract_outputs(
    run: Any,
    outputs_cfg: Any,
) -> dict[str, tuple[float, ...]]:
    """Extract simulated observables from a finished :class:`Run`.

    Each declared output is read from the catalog via
    :meth:`Run.timeseries`, :meth:`Run.budget` or :meth:`Run.field` and
    returned as a stable float tuple. Outputs unavailable in the catalog
    (e.g. solver-specific budget components missing for a given package)
    collapse to a NaN-padded vector of the expected length so the calling
    objective machinery can still produce a finite cost.

    Parameters
    ----------
    run
        Catalog :class:`hydromodpy.results.run.Run` for the candidate.
    outputs_cfg
        Iterable of output declarations or mapping ``{name: decl}``.
        Each declaration must expose ``variable``, ``support``, and the
        usual point/boundary/cell coordinates.
    """
    # Normalise the configuration object to an iterable of (name, decl).
    if hasattr(outputs_cfg, "items") and not hasattr(outputs_cfg, "support"):
        items = list(outputs_cfg.items())
    else:
        items = []
        for entry in outputs_cfg:
            name = getattr(entry, "name", None)
            if name is None:
                continue
            items.append((str(name), entry))

    selected: dict[str, tuple[float, ...]] = {}
    for name, decl in items:
        variable = str(getattr(decl, "variable", "")).strip().lower()
        support = str(getattr(decl, "support", "point")).strip().lower()
        observed = getattr(decl, "observed_values", None)
        expected_length = len(observed) if observed is not None else 1
        values: np.ndarray | None = None
        try:
            if variable == "outlet_discharge" or support == "boundary":
                values = _extract_outlet_discharge_from_run(
                    run,
                    boundary_id=str(getattr(decl, "boundary_id", "") or ""),
                )
            elif variable in {"watertable_elevation", "head"} and support == "point":
                values = _extract_head_at_point_from_run(
                    run,
                    x=float(_quantity_magnitude(getattr(decl, "x", None)) or 0.0),
                    y=float(_quantity_magnitude(getattr(decl, "y", None)) or 0.0),
                )
        except Exception:
            values = None
        if values is None or values.size == 0:
            values = np.full(expected_length, np.nan, dtype=float)
        selected[str(name)] = tuple(float(item) for item in np.asarray(values).ravel())
    return selected


def _quantity_magnitude(value: Any) -> float | None:
    """Coerce a pint-like quantity or bare number to a float magnitude."""
    if value is None:
        return None
    to_m = getattr(value, "to", None)
    if callable(to_m):
        try:
            return float(value.to("m").magnitude)
        except Exception:
            pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_outlet_discharge_from_run(run: Any, *, boundary_id: str) -> np.ndarray | None:
    """Sum boundary flux per timestep from ``run.budget()``."""
    bud = run.budget()
    if bud is None or bud.empty:
        return None
    preferred: tuple[str, ...] = ("drn", "drain", "drains", "chd")
    lowered = {str(c).strip().lower() for c in bud["component"].unique() if c is not None}
    bid = (boundary_id or "").strip().lower()
    resolved: str | None = None
    if "drain" in bid or "drn" in bid:
        for key in ("drn", "drain", "drains"):
            if key in lowered:
                resolved = key
                break
    if resolved is None:
        for key in preferred:
            if key in lowered:
                resolved = key
                break
    if resolved is None:
        return None
    subset = bud[bud["component"].astype(str).str.strip().str.lower() == resolved]
    if subset.empty:
        return None
    grouped = subset.groupby("timestep", as_index=True)
    flux = grouped["flux_out"].sum().sort_index()
    return flux.to_numpy(dtype=float)


def _extract_head_at_point_from_run(run: Any, *, x: float, y: float) -> np.ndarray | None:
    """Read a head time series at the cell closest to ``(x, y)`` from a Run."""
    flat_index: int | None = None
    try:
        grid = run.grid
    except Exception:
        grid = None
    if grid is not None and getattr(grid, "cell_size", None) and getattr(grid, "extent", None):
        try:
            cell_size = float(grid.cell_size)
            x_min, _, y_min, _ = (float(v) for v in grid.extent)
            n_rows, n_cols = (int(v) for v in grid.shape)
            col = int(round((float(x) - x_min) / cell_size - 0.5))
            row_from_bottom = int(round((float(y) - y_min) / cell_size - 0.5))
            col = max(0, min(n_cols - 1, col))
            row_from_bottom = max(0, min(n_rows - 1, row_from_bottom))
            row = n_rows - 1 - row_from_bottom
            flat_index = int(row * n_cols + col)
        except Exception:
            flat_index = None
    if flat_index is None:
        try:
            mesh_payload = run.mesh
        except Exception:
            mesh_payload = None
        if mesh_payload is not None:
            vertices = np.asarray(mesh_payload.vertices, dtype=float)
            connectivity = np.asarray(mesh_payload.face_node_connectivity, dtype=int)
            if connectivity.size and vertices.size >= 2:
                valid = connectivity >= 0
                gathered = np.where(
                    valid[..., None],
                    vertices[np.where(valid, connectivity, 0)],
                    np.nan,
                )
                centroids = np.nanmean(gathered, axis=1)[:, :2]
                if centroids.size:
                    distances = np.hypot(
                        centroids[:, 0] - float(x),
                        centroids[:, 1] - float(y),
                    )
                    flat_index = int(np.argmin(distances))
    if flat_index is None:
        return None

    n_ts = 1
    try:
        row = run._load_row() if hasattr(run, "_load_row") else {}
        row_ts = row.get("n_timesteps") if row else None
        if row_ts is not None:
            n_ts = max(1, int(row_ts))
    except Exception:
        n_ts = 1

    for variable in ("head", "watertable_elevation"):
        values: list[float] = []
        ok = True
        for t in range(n_ts):
            try:
                frame = run.field(variable, timestep=t)
            except Exception:
                ok = False
                break
            arr = np.asarray(frame, dtype=float).ravel()
            if flat_index >= arr.size:
                values.append(float("nan"))
            else:
                values.append(float(arr[flat_index]))
        if ok and values:
            out = np.asarray(values, dtype=float)
            out[np.abs(out) > 1e6] = np.nan
            return out
    return None


def _build_twin_metric_fn(
    *,
    output_decls: tuple[tuple[str, Any], ...],
    objective_blocks: tuple[Any, ...],
):
    """Build a custom ``metric_fn`` that uses filesystem-based extraction.

    The default :func:`hydromodpy.calibration.metrics.build_metric_extractor`
    is MODFLOW-NWT specific; the twin benchmarks target MODFLOW 6 in
    lightweight trial mode (no catalog ingest), so we read the CBC
    budget and head-save (HDS) files directly from the trial's
    ``output_dirs_by_run_id`` and assemble the composite via
    :class:`ConfigBlockObjective`.
    """
    from hydromodpy.calibration.objective import ConfigBlockObjective

    block_objectives: list[ConfigBlockObjective] = []
    raw_weights: list[float] = []
    for block in objective_blocks:
        observed_by_output: dict[str, list[float]] = {}
        for output_name in block.uses_outputs:
            decl = next((d for d in output_decls if d[0] == output_name), None)
            if decl is None:
                continue
            obs = getattr(decl[1], "observed_values", None) or ()
            observed_by_output[output_name] = [float(value) for value in obs]
        block_objectives.append(
            ConfigBlockObjective(
                name=block.name,
                metric=block.metric,
                uses_outputs=tuple(block.uses_outputs),
                observed_by_output=observed_by_output,
                normalize_cost=bool(block.normalize_cost),
                transform=str(getattr(block, "transform", "identity")),
            )
        )
        raw_weights.append(float(block.weight))
    weights = np.asarray(raw_weights, dtype=float)
    weight_sum = float(weights.sum())
    if weight_sum <= 0.0:
        raise ValueError("Composite objective requires a strictly positive total weight")
    normalized_weights = weights / weight_sum

    def metric_fn(trial_ctx: Any, *, objective: str | None = None, variable: str | None = None):
        del objective, variable
        try:
            selected = _extract_outputs_from_trial_ctx(
                trial_ctx=trial_ctx,
                output_decls=output_decls,
            )
        except Exception as exc:
            return float("nan"), {"__error__": f"{type(exc).__name__}: {exc}"}

        components: dict[str, float] = {}
        block_costs: list[float] = []
        for block in block_objectives:
            try:
                value = block.evaluate(selected)
            except Exception as exc:
                return float("nan"), {"__error__": f"{type(exc).__name__}: {exc}"}
            block_costs.append(float(value.total))
            for cname, cvalue in value.components.items():
                components[str(cname)] = float(cvalue)
        if not block_costs:
            return float("nan"), components
        total = float(np.sum(normalized_weights * np.asarray(block_costs, dtype=float)))
        components["__weighted_total__"] = total
        return total, components

    return metric_fn


def _extract_outputs_from_trial_ctx(
    *,
    trial_ctx: Any,
    output_decls: tuple[tuple[str, Any], ...],
) -> dict[str, list[float]]:
    """Read configured outputs from the trial's solver output directory."""
    registry = getattr(trial_ctx, "execution", None)
    output_dirs = getattr(registry, "output_dirs_by_run_id", None) or {}
    models = getattr(registry, "models_by_run_id", None) or {}
    plan = getattr(registry, "simulation_plan", None)
    flow_run_id: str | None = None
    if plan is not None:
        for run in getattr(plan, "runs", ()):
            if run.process_type == "flow" and run.id in output_dirs:
                flow_run_id = run.id
                break
    if flow_run_id is None and output_dirs:
        flow_run_id = next(iter(output_dirs.keys()))
    if flow_run_id is None:
        out: dict[str, list[float]] = {}
        for name, decl in output_decls:
            observed = getattr(decl, "observed_values", None)
            length = len(observed) if observed is not None else 1
            out[str(name)] = [float("nan")] * length
        return out
    output_dir = Path(output_dirs[flow_run_id])
    model = models.get(flow_run_id)
    model_name = (
        getattr(model, "model_name", None) or getattr(model, "name", None) if model else None
    )
    mesh_planar = getattr(getattr(trial_ctx, "setup", None), "mesh_planar", None)

    selected: dict[str, list[float]] = {}
    for name, decl in output_decls:
        variable = str(getattr(decl, "variable", "")).strip().lower()
        support = str(getattr(decl, "support", "point")).strip().lower()
        observed = getattr(decl, "observed_values", None)
        expected_len = len(observed) if observed is not None else 1
        values: np.ndarray | None = None
        if model_name is not None:
            try:
                if variable == "outlet_discharge" or support == "boundary":
                    values = _extract_outlet_discharge_from_dir(
                        output_dir,
                        model_name,
                    )
                elif variable in {"watertable_elevation", "head"} and support == "point":
                    values = _extract_head_at_point_from_dir(
                        output_dir,
                        model_name,
                        x=float(_quantity_magnitude(getattr(decl, "x", None)) or 0.0),
                        y=float(_quantity_magnitude(getattr(decl, "y", None)) or 0.0),
                        model=model,
                        mesh_planar=mesh_planar,
                    )
            except Exception:
                values = None
        if values is None or values.size == 0:
            values = np.full(expected_len, np.nan, dtype=float)
        selected[str(name)] = [float(v) for v in np.asarray(values).ravel()]
    return selected


def _extract_outlet_discharge_from_dir(
    output_dir: Path,
    model_name: str,
) -> np.ndarray | None:
    """Sum boundary flux per timestep from a CBC budget file in ``output_dir``."""
    try:
        import flopy.utils.binaryfile as bf
    except Exception:
        return None
    cbc_path: Path | None = None
    for extension in ("cbc", "cbb"):
        candidate = output_dir / f"{model_name}.{extension}"
        if candidate.exists():
            cbc_path = candidate
            break
    if cbc_path is None:
        return None
    cbb = bf.CellBudgetFile(str(cbc_path))
    try:
        record_names = [r.decode().strip().lower() for r in cbb.get_unique_record_names()]
        record_name: str | None = None
        for key in ("drn", "drain", "drains", "chd"):
            for rec in record_names:
                if key in rec:
                    record_name = rec
                    break
            if record_name is not None:
                break
        if record_name is None:
            return None
        times = cbb.get_times()
        kstpkpers = cbb.get_kstpkper()
        values = np.zeros(len(times), dtype=float)
        for t, (totim, ksk) in enumerate(zip(times, kstpkpers, strict=False)):
            try:
                data = cbb.get_data(text=record_name, kstpkper=ksk, totim=totim, full3D=True)
            except Exception:
                continue
            if not data:
                continue
            arr = np.asarray(data[0], dtype=float)
            values[t] = float(np.abs(np.minimum(arr, 0.0)).sum())
    finally:
        cbb.close()
    return values


def _extract_head_at_point_from_dir(
    output_dir: Path,
    model_name: str,
    *,
    x: float,
    y: float,
    model: Any = None,
    mesh_planar: Any = None,
) -> np.ndarray | None:
    """Read a head time series at the cell closest to ``(x, y)`` from an HDS file.

    Returns the watertable elevation (raw head clipped to the per-cell top).
    Truth synthesis goes through ``Run.field('watertable_elevation')`` which
    applies the same clip; clipping here keeps the calibration cost surface
    bit-identical to the truth observations when the unconfined head reaches
    the ground surface.

    Resolves the cell index from the solver model's mesh first - the
    lightweight v0.6 trial pipeline never populates ``setup.mesh_planar`` for
    ``sgrid`` simulations, so the registered solver model is the only place
    where the grid layout is exposed at trial time. Falls back to
    ``mesh_planar`` for legacy callers (catchment-scale runs).

    Indexes the head array by inspecting its shape: structured DIS arrays
    are ``(nlay, nrow, ncol)`` while DISV arrays come back as
    ``(nlay, 1, ncpl)`` from flopy, so the row / col split must collapse to
    a flat ncpl index when the middle axis is degenerate.
    """
    try:
        import flopy.utils.binaryfile as bf
    except Exception:
        return None
    hds_path = output_dir / f"{model_name}.hds"
    if not hds_path.exists():
        return None
    cell_index = _resolve_cell_index_from_model(model, x=x, y=y)
    if cell_index is None:
        cell_index = _nearest_cell_index_legacy(mesh_planar, x=x, y=y)
    if cell_index is None:
        return None
    k, i, j, flat = cell_index
    ncol_hint = int(getattr(model, "ncol", 0) or 0) if model is not None else 0
    cell_top = _resolve_cell_top_from_dir(output_dir, model_name, flat_index=flat)
    hf = bf.HeadFile(str(hds_path))
    try:
        times = hf.get_times()
        values = np.full(len(times), np.nan, dtype=float)
        for t, totim in enumerate(times):
            try:
                head = hf.get_data(totim=totim)
                values[t] = _read_head_at_cell(
                    head,
                    layer=k,
                    row=i,
                    col=j,
                    flat_index=flat,
                    ncol_hint=ncol_hint,
                )
            except Exception:
                pass
        values[np.abs(values) > 1e6] = np.nan
        if cell_top is not None and np.isfinite(cell_top):
            values = np.minimum(values, float(cell_top))
    finally:
        hf.close()
    return values


def _resolve_cell_top_from_dir(
    output_dir: Path, model_name: str, *, flat_index: int
) -> float | None:
    """Return the surface elevation (top) at one cell, read from the GRB file.

    Mirrors :func:`hydromodpy.solver.modflow6.extractors.flow._write_surface_elevation`:
    the GRB grid metadata exposes ``top1d`` (DISV) or ``top`` (DIS) which
    feed :func:`hydromodpy.results.derived.watertable_elevation`. Returning
    a finite value here lets the trial-time HDS reader apply the same
    ``min(head, top)`` clip the catalog applies.
    """
    grb_files = list(output_dir.glob(f"{model_name}.dis.grb")) + list(
        output_dir.glob(f"{model_name}.disv.grb")
    )
    if not grb_files:
        return None
    try:
        try:
            from flopy.mf6.utils import MfGrdFile
        except ImportError:
            from flopy.utils import MfGrdFile

        grd = MfGrdFile(str(grb_files[0]))
        top_raw = getattr(grd, "top1d", None)
        if top_raw is None:
            top_raw = grd.top
        top = np.asarray(top_raw, dtype="float64").ravel()
    except Exception:
        return None
    if top.size == 0 or flat_index < 0 or flat_index >= top.size:
        return None
    return float(top[flat_index])


def _read_head_at_cell(
    head: np.ndarray,
    *,
    layer: int,
    row: int,
    col: int,
    flat_index: int,
    ncol_hint: int,
) -> float:
    """Index a head array using a structured ``(layer, row, col)`` plus a flat fallback.

    Flopy returns DIS heads as ``(nlay, nrow, ncol)`` but DISV heads as
    ``(nlay, 1, ncpl)``. When the middle axis is degenerate the structured
    ``(row, col)`` decomposition collapses to ``flat_index`` along the ncpl
    axis. The 2D / 1D shapes are kept as a defensive fallback.
    """
    arr = np.asarray(head)
    if arr.ndim == 3:
        if arr.shape[1] == 1 and flat_index < arr.shape[2]:
            return float(arr[layer, 0, flat_index])
        return float(arr[layer, row, col])
    if arr.ndim == 2:
        return float(arr[layer, flat_index])
    return float(arr.ravel()[flat_index])


def _resolve_cell_index_from_model(
    model: Any,
    *,
    x: float,
    y: float,
) -> tuple[int, int, int, int] | None:
    """Return ``(layer, row, col, flat_index)`` for a registered solver model.

    Reads the structured layout (``nrow`` / ``ncol``) and the cell centroids
    from the solver model registered in ``execution.models_by_run_id``. Works
    for MODFLOW 6 (``solver_mesh.cell_centroids()``) and MODFLOW-NWT
    (``runtime_mesh_planar`` / direct ``cell_centroids``). The ``flat_index``
    is the cell rank in ``cell_centroids`` and is the right axis-2 offset for
    DISV heads.
    """
    if model is None:
        return None
    centroids = _model_cell_centroids(model)
    if centroids is None:
        return None
    arr = np.asarray(centroids, dtype=float).reshape(-1, 2)
    if arr.size == 0:
        return None
    nrow = int(getattr(model, "nrow", 0) or 0)
    ncol = int(getattr(model, "ncol", 0) or 0)
    if nrow > 0 and ncol > 0 and arr.shape[0] == nrow * ncol:
        x_unique = np.unique(arr[:, 0])
        y_unique = np.unique(arr[:, 1])
        if x_unique.size == ncol and y_unique.size == nrow:
            cell_dx = float(x_unique[1] - x_unique[0]) if ncol > 1 else 1.0
            cell_dy = float(y_unique[1] - y_unique[0]) if nrow > 1 else 1.0
            x_min = float(x_unique[0] - cell_dx / 2.0)
            y_min = float(y_unique[0] - cell_dy / 2.0)
            col = int(round((float(x) - x_min) / cell_dx - 0.5))
            row = int(round((float(y) - y_min) / cell_dy - 0.5))
            col = max(0, min(ncol - 1, col))
            row = max(0, min(nrow - 1, row))
            flat = row * ncol + col
            return (0, row, col, flat)
    distances = np.hypot(arr[:, 0] - float(x), arr[:, 1] - float(y))
    flat_index = int(np.argmin(distances))
    if nrow > 0 and ncol > 0 and flat_index < nrow * ncol:
        return (0, flat_index // ncol, flat_index % ncol, flat_index)
    return (0, 0, flat_index, flat_index)


def _model_cell_centroids(model: Any) -> np.ndarray | None:
    """Return cell centroids ``(n_cells, 2)`` from a solver model, if exposed."""
    solver_mesh = getattr(model, "solver_mesh", None)
    if solver_mesh is not None:
        accessor = getattr(solver_mesh, "cell_centroids", None)
        if callable(accessor):
            try:
                return np.asarray(accessor(), dtype=float)
            except Exception:
                return None
        if accessor is not None:
            try:
                return np.asarray(accessor, dtype=float)
            except Exception:
                return None
    runtime_planar = getattr(model, "runtime_mesh_planar", None)
    if runtime_planar is not None:
        legacy = getattr(runtime_planar, "cell_centroids", None)
        if legacy is None:
            legacy = getattr(runtime_planar, "centroids", None)
        if legacy is not None:
            try:
                return np.asarray(legacy, dtype=float)
            except Exception:
                return None
    return None


def _nearest_cell_index_legacy(
    mesh: Any,
    *,
    x: float,
    y: float,
) -> tuple[int, int, int, int] | None:
    """Return ``(layer, row, col, flat_index)`` of the cell closest to ``(x, y)``."""
    if mesh is None:
        return None
    centroids = getattr(mesh, "cell_centroids", None)
    if centroids is None:
        centroids = getattr(mesh, "centroids", None)
    if centroids is None:
        return None
    arr = np.asarray(centroids, dtype=float)
    if arr.ndim != 2 or arr.shape[1] < 2:
        return None
    distances = np.hypot(arr[:, 0] - float(x), arr[:, 1] - float(y))
    flat_index = int(np.argmin(distances))
    shape = getattr(mesh, "shape", None)
    if shape is None or len(shape) < 2:
        return (0, 0, flat_index, flat_index)
    _, n_rows, n_cols = shape if len(shape) == 3 else (1, *shape)
    layer = 0
    row = flat_index // n_cols
    col = flat_index % n_cols
    return (layer, int(row), int(col), flat_index)


def _make_instrumented_run_trial_light(
    original_fn: Any,
    state: dict[str, float],
) -> Any:
    """Wrap ``run_trial_light`` to record per-iteration timing into ``state``."""

    def _instrumented(
        trial_ctx: Any,
        values: Any,
        *,
        objective: str = "nse",
        variable: str = "head",
        metric_fn: Any = None,
    ) -> Any:
        state["t_start"] = time.perf_counter()
        state["t_run_start"] = time.perf_counter()
        return original_fn(
            trial_ctx,
            values,
            objective=objective,
            variable=variable,
            metric_fn=metric_fn,
        )

    return _instrumented


def _normalise_outputs_for_extraction(
    outputs_cfg: Any,
    *,
    observed_values: dict[str, tuple[float, ...]] | None = None,
) -> tuple[tuple[str, Any], ...]:
    """Return ``[(name, decl)]`` pairs accepted by the bridge extractor.

    The optional ``observed_values`` mapping overrides each declaration's
    ``observed_values`` attribute - used to inject the truth-synthesis
    output before passing the decls to :func:`_build_twin_metric_fn`.
    """
    if hasattr(outputs_cfg, "items"):
        out: list[tuple[str, Any]] = []
        for name, decl in outputs_cfg.items():
            obs = (
                tuple(float(value) for value in observed_values[str(name)])
                if observed_values is not None and str(name) in observed_values
                else getattr(decl, "observed_values", None)
            )
            wrapper = type(
                "_DeclShim",
                (),
                {
                    "name": str(name),
                    "variable": str(getattr(decl, "variable", "")),
                    "support": str(getattr(decl, "support", "point")),
                    "x": _quantity_magnitude(getattr(decl, "x", None)),
                    "y": _quantity_magnitude(getattr(decl, "y", None)),
                    "boundary_id": getattr(decl, "boundary_id", None),
                    "time": getattr(decl, "time", "all"),
                    "reducer": getattr(decl, "reducer", None),
                    "observed_values": obs,
                },
            )()
            out.append((str(name), wrapper))
        return tuple(out)
    return tuple()


def _write_calibration_toml_for_project(
    *,
    benchmark_root: Path,
    method_instance_name: str,
    payload: dict[str, Any],
    simulation_config_name: str,
    workspace_root: Path,
) -> Path:
    """Materialise the calibration TOML on disk next to the simulation."""
    calibration_path = benchmark_root / f"calibration_case_{method_instance_name}.toml"
    rendered: dict[str, Any] = {
        "base_config": str(simulation_config_name),
        "workspace": {"root": str(workspace_root)},
        "calibration": payload["calibration"],
    }
    _write_toml(calibration_path, rendered)
    return calibration_path


def _assess_method_result_from_report(
    *,
    definition: TwinCalibrationCaseDefinition,
    method_profile: CalibrationMethodProfile,
    method_instance_name: str,
    repeat_index: int,
    seed: int | None,
    effective_method_kwargs: dict[str, Any],
    requested_evaluation_budget: int | None,
    report: Any,
    iterations_df: Any,
    calibration_id: str,
    calibration_path: Path,
    candidate_timing_values: list[dict[str, float]],
    session_prepare_time_seconds: float,
    output_decls: tuple[tuple[str, Any], ...],
) -> TwinMethodBenchmarkResult:
    """Convert one :class:`CalibrationReport` into a :class:`TwinMethodBenchmarkResult`."""
    truth_params = {str(name): float(value) for name, value in definition.truth_params.items()}
    abs_tolerances = {
        str(name): float(value) for name, value in definition.parameter_abs_tolerances.items()
    }

    # Iteration history -> best record.
    iteration_count = int(len(iterations_df))
    completed_mask = iterations_df["status"] == "completed"
    completed_df = iterations_df[completed_mask]
    cost_best = (
        None
        if report.best_objective is None or not math.isfinite(float(report.best_objective))
        else float(report.best_objective)
    )
    params_best: dict[str, float] = {}
    if not completed_df.empty:
        best_idx = completed_df["objective_value"].astype(float).idxmin()
        best_row = iterations_df.loc[best_idx]
        params_named = best_row.get("parameters") or {}
        if isinstance(params_named, str):
            try:
                params_named = json.loads(params_named)
            except json.JSONDecodeError:
                params_named = {}
        params_best = {
            str(name): float(value)
            for name, value in dict(params_named).items()
            if value is not None
        }
    param_abs_error = _param_abs_error(
        truth_params=truth_params,
        params_best=params_best,
    )
    recovered_truth = bool(
        cost_best is not None
        and math.isfinite(cost_best)
        and all(
            math.isfinite(param_abs_error.get(name, math.inf))
            and param_abs_error[name] <= abs_tolerances[name]
            for name in truth_params
        )
    )

    n_evaluations = int(len(completed_df))
    if n_evaluations == 0:
        n_evaluations = iteration_count

    # Timing aggregates from candidate timing list.
    candidate_timing_summary = _summarize_candidate_timings_for_report(candidate_timing_values)
    mean_total = candidate_timing_summary.get("total_time_seconds")
    mean_prep = candidate_timing_summary.get("prepare_time_seconds")
    mean_sim = candidate_timing_summary.get("simulation_time_seconds")

    calibration_time_seconds = float(report.duration_s)
    time_per_evaluation_seconds = (
        None if n_evaluations <= 0 else float(calibration_time_seconds) / float(n_evaluations)
    )
    candidate_run_count = int(len(candidate_timing_values))
    estimated_candidate_runtime_seconds = _estimate_candidate_runtime_seconds(
        mean_candidate_total_time_seconds=mean_total,
        candidate_run_count=candidate_run_count,
        n_evaluations=int(n_evaluations),
    )
    algorithm_overhead_time_seconds = _algorithm_overhead_time_seconds(
        calibration_time_seconds=calibration_time_seconds,
        estimated_candidate_runtime_seconds=estimated_candidate_runtime_seconds,
    )

    # Block-level fields from the iteration metrics column.
    block_raw_cost_best: dict[str, float] = {}
    block_normalized_cost_best: dict[str, float] = {}
    block_reference_scale: dict[str, float] = {}
    block_n_values: dict[str, int] = {}
    if not completed_df.empty:
        best_idx = completed_df["objective_value"].astype(float).idxmin()
        metrics_payload = iterations_df.loc[best_idx].get("metrics")
        if isinstance(metrics_payload, str):
            try:
                metrics_payload = json.loads(metrics_payload)
            except json.JSONDecodeError:
                metrics_payload = None
        if isinstance(metrics_payload, dict):
            block_costs_payload = metrics_payload.get("block_costs", {}) or {}
            for cname, cvalue in block_costs_payload.items():
                if cname.endswith(".raw_cost"):
                    block_raw_cost_best[cname[: -len(".raw_cost")]] = float(cvalue)
                elif cname.endswith(".normalized_cost"):
                    block_normalized_cost_best[cname[: -len(".normalized_cost")]] = float(cvalue)
                elif cname.endswith(".reference_scale"):
                    block_reference_scale[cname[: -len(".reference_scale")]] = float(cvalue)
                elif cname.endswith(".n_values"):
                    block_n_values[cname[: -len(".n_values")]] = int(float(cvalue))

    # Optional model distribution from completed iterations.
    distribution_path: Path | None = None
    distribution_sample_count = 0
    truth_in_distribution: bool | None = None
    truth_distribution_min_abs_error: dict[str, float] = {}
    if method_profile.persist_model_distribution and not completed_df.empty:
        samples: list[dict[str, Any]] = []
        for _, row in completed_df.iterrows():
            params_named = row.get("parameters") or {}
            if isinstance(params_named, str):
                try:
                    params_named = json.loads(params_named)
                except json.JSONDecodeError:
                    params_named = {}
            samples.append(
                {
                    "sample_id": f"iter_{int(row['iteration']):04d}",
                    "params_named": {str(k): float(v) for k, v in dict(params_named).items()},
                    "objective_total": (
                        None
                        if row["objective_value"] is None
                        or not math.isfinite(float(row["objective_value"]))
                        else float(row["objective_value"])
                    ),
                }
            )
        distribution_path = (
            calibration_path.parent / f"model_distribution_{method_instance_name}.json"
        )
        distribution_path.write_text(
            json.dumps(
                {
                    "role": "parameter_sample_distribution",
                    "method": str(method_profile.name),
                    "samples": samples,
                },
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )
        distribution_sample_count = int(len(samples))
        truth_in_distribution_local = False
        min_errors_local = {str(name): math.inf for name in truth_params}
        for sample in samples:
            params_named = sample.get("params_named", {})
            sample_ok = True
            for name, truth in truth_params.items():
                value = params_named.get(name)
                if value is None:
                    sample_ok = False
                    continue
                error = abs(float(value) - float(truth))
                if error < min_errors_local[name]:
                    min_errors_local[name] = float(error)
                if error > float(abs_tolerances[name]):
                    sample_ok = False
            if sample_ok:
                truth_in_distribution_local = True
        truth_in_distribution = truth_in_distribution_local
        truth_distribution_min_abs_error = {
            name: float(value) for name, value in min_errors_local.items() if math.isfinite(value)
        }

    success_metric = str(method_profile.success_metric).strip().lower()
    if success_metric == "best_fit":
        meets_success_target = recovered_truth
    elif success_metric == "distribution":
        meets_success_target = truth_in_distribution is True
    elif success_metric == "best_fit_or_distribution":
        meets_success_target = recovered_truth or truth_in_distribution is True
    else:
        raise ValueError(
            f"Unsupported calibration benchmark success_metric '{method_profile.success_metric}'."
        )

    iteration_history_path = (
        calibration_path.parent / f"iteration_history_{method_instance_name}.jsonl"
    )
    _write_iteration_history_jsonl(
        path=iteration_history_path,
        iterations_df=iterations_df,
    )

    failed_iteration_count = int((~completed_mask).sum())
    return TwinMethodBenchmarkResult(
        method_name=method_profile.name,
        method_instance_name=method_instance_name,
        success_metric=success_metric,
        effective_method_kwargs={
            str(name): value for name, value in effective_method_kwargs.items()
        },
        requested_evaluation_budget=requested_evaluation_budget,
        calibration_id=str(calibration_id),
        calibration_root=calibration_path.parent,
        result_path=calibration_path,
        cost_best=cost_best,
        iteration_count=iteration_count,
        n_evaluations=n_evaluations,
        params_best=params_best,
        param_abs_error=param_abs_error,
        recovered_truth=recovered_truth,
        repeat_index=int(repeat_index),
        seed=seed,
        calibration_time_seconds=calibration_time_seconds,
        time_per_evaluation_seconds=time_per_evaluation_seconds,
        session_prepare_time_seconds=float(session_prepare_time_seconds),
        estimated_candidate_runtime_seconds=estimated_candidate_runtime_seconds,
        algorithm_overhead_time_seconds=algorithm_overhead_time_seconds,
        mean_candidate_total_time_seconds=mean_total,
        mean_candidate_preparation_time_seconds=mean_prep,
        mean_candidate_simulation_time_seconds=mean_sim,
        mean_candidate_actualize_time_seconds=mean_prep,
        mean_candidate_launcher_prepare_time_seconds=mean_prep,
        mean_candidate_runtime_patch_time_seconds=0.0,
        mean_candidate_output_selection_time_seconds=0.0,
        mean_candidate_objective_build_time_seconds=0.0,
        mean_candidate_objective_compute_time_seconds=0.0,
        mean_candidate_objective_time_seconds=0.0,
        failed_iteration_count=failed_iteration_count,
        meets_success_target=bool(meets_success_target),
        candidate_run_count=candidate_run_count,
        objective_cache_hit_count=0,
        objective_cache_hit_rate=None,
        block_raw_cost_best=block_raw_cost_best,
        block_normalized_cost_best=block_normalized_cost_best,
        block_reference_scale=block_reference_scale,
        block_n_values=block_n_values,
        iteration_history_path=iteration_history_path,
        model_distribution_path=distribution_path,
        model_distribution_sample_count=distribution_sample_count,
        truth_in_distribution=truth_in_distribution,
        truth_distribution_min_abs_error=truth_distribution_min_abs_error,
    )


def _summarize_candidate_timings_for_report(
    values: list[dict[str, float]],
) -> dict[str, float | None]:
    """Aggregate per-candidate timing dicts into mean values."""
    if not values:
        return {
            "total_time_seconds": None,
            "prepare_time_seconds": None,
            "simulation_time_seconds": None,
        }
    keys = ("total_time_seconds", "prepare_time_seconds", "simulation_time_seconds")
    summary: dict[str, float | None] = {}
    for key in keys:
        series = [float(entry[key]) for entry in values if entry.get(key) is not None]
        summary[key] = float(np.mean(series)) if series else None
    return summary


def _write_iteration_history_jsonl(
    *,
    path: Path,
    iterations_df: Any,
) -> None:
    """Write the iteration trace as a legacy-shaped JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for _, row in iterations_df.iterrows():
            params_named = row.get("parameters") or {}
            if isinstance(params_named, str):
                try:
                    params_named = json.loads(params_named)
                except json.JSONDecodeError:
                    params_named = {}
            metrics_payload = row.get("metrics") or {}
            if isinstance(metrics_payload, str):
                try:
                    metrics_payload = json.loads(metrics_payload)
                except json.JSONDecodeError:
                    metrics_payload = {}
            obj = row.get("objective_value")
            try:
                obj_value = None if obj is None or not math.isfinite(float(obj)) else float(obj)
            except (TypeError, ValueError):
                obj_value = None
            block_costs = {}
            if isinstance(metrics_payload, dict):
                inner = metrics_payload.get("block_costs", {})
                if isinstance(inner, dict):
                    block_costs = {str(k): v for k, v in inner.items()}
            stream.write(
                json.dumps(
                    {
                        "iteration_id": f"iter_{int(row['iteration']):04d}",
                        "params_named": dict(params_named),
                        "params_vector": [
                            float(v) for v in dict(params_named).values() if v is not None
                        ],
                        "objective_total": obj_value,
                        "block_costs": block_costs,
                        "status": str(row.get("status") or "unknown"),
                        "failure_reason": (
                            None if row.get("status") == "completed" else str(row.get("status"))
                        ),
                    },
                    ensure_ascii=True,
                )
                + "\n"
            )


def synthesize_truth_observations_via_project_api(
    *,
    definition: TwinCalibrationCaseDefinition,
    truth_simulation_config_path: Path,
    benchmark_root: Path,
) -> dict[str, dict[str, tuple[float, ...]]]:
    """Run the truth candidate via :class:`hydromodpy.Project` and extract observables.

    Materializes the truth K via
    :func:`hydromodpy.calibration.materialize.materialize_candidate`,
    runs :class:`hydromodpy.Project` on the resulting overlay, and pulls
    each observable through :func:`extract_outputs`.
    """
    from hydromodpy.calibration.materialize import materialize_candidate
    from hydromodpy.calibration.parameters import ParameterSpace
    from hydromodpy.project import Project as _Project

    if definition.parameter_targets is None:
        raise ValueError(
            f"synthesize_truth_observations_via_project_api requires "
            f"definition.parameter_targets for {definition.case_id!r}."
        )
    if definition.output_specs is None:
        raise ValueError(
            f"synthesize_truth_observations_via_project_api requires "
            f"definition.output_specs for {definition.case_id!r}."
        )

    declarations = {}
    for name, target in definition.parameter_targets.items():
        low, high = definition.bounds[name]
        decl: dict[str, Any] = {
            "bounds": [float(low), float(high)],
            "target": str(target.target),
            "mode": str(target.mode),
        }
        if target.transform is not None:
            decl["transform"] = str(target.transform)
        declarations[str(name)] = decl
    space = ParameterSpace.from_toml_mapping(declarations)

    truth_root = benchmark_root / "truth_candidate"
    truth_root.mkdir(parents=True, exist_ok=True)
    overlay_path = materialize_candidate(
        truth_simulation_config_path,
        {str(name): float(value) for name, value in definition.truth_params.items()},
        space,
        truth_root,
        candidate_label="truth",
        workspace_root=benchmark_root / "project_truth",
        extra_sections={
            "display": {"enabled": False, "show": False, "save": False},
            "postprocess": {"enabled": False},
            "simulation": {"run_id": "twin_truth"},
        },
    )

    project = _Project(overlay_path, headless=True)
    try:
        run = project.run()
        selected = extract_outputs(run, definition.output_specs)
    finally:
        project.close()

    output_decls = _normalise_outputs_for_extraction(definition.output_specs)
    clean_observations = {
        str(name): tuple(float(value) for value in values) for name, values in selected.items()
    }
    used_observations = _apply_observation_noise(
        clean_observations,
        noise=definition.observation_noise,
    )
    truth_output_path = benchmark_root / "truth_observations.json"
    truth_output_path.write_text(
        json.dumps(
            {
                "role": "synthetic_truth_observations",
                "case_id": definition.case_id,
                "solver_name": definition.solver_name,
                "truth_simulation_config_path": str(truth_simulation_config_path),
                "truth_params": {
                    str(name): float(value) for name, value in definition.truth_params.items()
                },
                "observations_truth": {
                    str(name): [float(value) for value in values]
                    for name, values in clean_observations.items()
                },
                "observations_used": {
                    str(name): [float(value) for value in values]
                    for name, values in used_observations.items()
                },
                "output_decl_count": len(output_decls),
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"truth": clean_observations, "used": used_observations}


def run_twin_benchmark_case(
    definition: TwinCalibrationCaseDefinition,
    *,
    caller_file: str | Path,
    method_names: tuple[str, ...] | None = None,
    evaluation_budget: int | None = None,
    artifact_retention: str | None = None,
    case_figures: bool | None = None,
    figure_format: str = "png",
) -> TwinCalibrationBenchmarkResult:
    """Run one twin benchmark via the :meth:`Project.calibrate` API.

    Routes through the v0.6 ``[calibration]`` schema +
    :class:`hydromodpy.Project`. The case definition must declare
    ``parameter_targets``, ``output_specs`` and ``objective_block_specs``
    so :func:`build_payload` can emit the enriched TOML.
    """
    del caller_file
    if definition.build_simulation_config is None:
        raise ValueError("Twin calibration case is missing build_simulation_config")
    if definition.parameter_targets is None or definition.output_specs is None:
        raise ValueError(
            f"run_twin_benchmark_case requires parameter_targets/output_specs on "
            f"{definition.case_id!r}."
        )
    if definition.objective_block_specs is None:
        raise ValueError(
            f"run_twin_benchmark_case requires objective_block_specs on {definition.case_id!r}."
        )

    benchmark_root = _resolve_twin_benchmark_root(definition)
    benchmark_root.mkdir(parents=True, exist_ok=True)
    simulation_config_path = benchmark_root / "simulation.toml"
    definition.build_simulation_config(
        simulation_config_path,
        benchmark_root / "project",
    )
    truth_builder = definition.build_truth_simulation_config
    if truth_builder is None:
        truth_simulation_config_path = simulation_config_path
    else:
        truth_simulation_config_path = benchmark_root / "truth_simulation.toml"
        truth_builder(
            truth_simulation_config_path,
            benchmark_root / "project_truth",
        )

    synthesized_observations = synthesize_truth_observations_via_project_api(
        definition=definition,
        truth_simulation_config_path=truth_simulation_config_path,
        benchmark_root=benchmark_root,
    )
    observations_truth = synthesized_observations["truth"]
    observations_used = synthesized_observations["used"]

    selected_profiles = tuple(definition.method_profiles)
    if method_names is not None:
        requested = {str(name).strip().lower() for name in method_names}
        selected_profiles = tuple(
            profile
            for profile in selected_profiles
            if str(profile.name).strip().lower() in requested
        )
    if not selected_profiles:
        raise ValueError(f"No method profile selected for benchmark '{definition.case_id}'.")

    retained_mode = (
        str(definition.artifact_retention)
        if artifact_retention is None
        else str(artifact_retention)
    )
    generate_case_figures = (
        definition.generate_case_figures if case_figures is None else bool(case_figures)
    )
    del figure_format  # case figures are skipped by default for the v0.6 path
    configuration_figure: Path | None = None
    reference_objective_path: Path | None = None
    if generate_case_figures:
        # Reuse the legacy plotting helpers when explicitly requested. Fall
        # back to None on the v0.6 path until the figure pipeline is ported.
        configuration_figure = None

    method_results: list[TwinMethodBenchmarkResult] = []
    for method_run in _iter_selected_method_runs(selected_profiles):
        method_profile = method_run["profile"]
        effective_profile = _apply_evaluation_budget(
            method_run["effective_profile"],
            n_parameters=len(definition.truth_params),
            evaluation_budget=evaluation_budget,
        )
        method_instance_name = str(method_run["instance_name"])
        repeat_index = int(method_run["repeat_index"])
        seed = method_run["seed"]
        calibration_id = _compact_calibration_id(
            definition,
            method_instance_name,
        )
        payload = build_payload(
            definition,
            simulation_config_name=simulation_config_path.name,
            calibration_id=calibration_id,
            observed_values=observations_used,
            method_profile=effective_profile,
        )
        calibration_path = _write_calibration_toml_for_project(
            benchmark_root=benchmark_root,
            method_instance_name=method_instance_name,
            payload=payload,
            simulation_config_name=simulation_config_path.name,
            workspace_root=benchmark_root / "project",
        )

        candidate_timing_values: list[dict[str, float]] = []
        candidate_run_state: dict[str, float] = {"t_start": 0.0, "t_run_start": 0.0}

        output_decls = _normalise_outputs_for_extraction(
            definition.output_specs,
            observed_values=observations_used,
        )
        custom_metric_fn = _build_twin_metric_fn(
            output_decls=output_decls,
            objective_blocks=tuple(definition.objective_block_specs),
        )

        def _make_timing_metric_fn(
            inner_metric_fn: Any,
            state: dict[str, float],
            timings: list[dict[str, float]],
        ) -> Any:
            def _timing_metric_fn(
                trial_ctx: Any,
                *,
                objective: str | None = None,
                variable: str | None = None,
            ) -> Any:
                sim_end = time.perf_counter()
                primary, components = inner_metric_fn(
                    trial_ctx,
                    objective=objective,
                    variable=variable,
                )
                sim_total = sim_end - state["t_run_start"]
                total = time.perf_counter() - state["t_start"]
                timings.append(
                    {
                        "total_time_seconds": float(total),
                        "prepare_time_seconds": max(0.0, float(total) - float(sim_total)),
                        "simulation_time_seconds": float(sim_total),
                    }
                )
                return primary, components

            return _timing_metric_fn

        timing_metric_fn = _make_timing_metric_fn(
            custom_metric_fn,
            candidate_run_state,
            candidate_timing_values,
        )

        # Prepare timing wrapper: monkey-patch run_trial_light per call to
        # capture per-iteration durations. Easier than modifying the engine.
        from hydromodpy.calibration.runners import trial as _trial_mod

        original_run_trial_light = _trial_mod.run_trial_light

        instrumented_run_trial_light = _make_instrumented_run_trial_light(
            original_run_trial_light,
            candidate_run_state,
        )

        from hydromodpy.calibration.runner import run_calibration_cli

        session_prepare_t0 = time.perf_counter()
        try:
            _trial_mod.run_trial_light = instrumented_run_trial_light
            report = run_calibration_cli(
                calibration_path,
                metric_fn=timing_metric_fn,
                workspace=benchmark_root / "project",
                project=str(definition.case_id),
                return_report=True,
            )
        finally:
            _trial_mod.run_trial_light = original_run_trial_light
        session_prepare_time_seconds = float(time.perf_counter() - session_prepare_t0)

        from hydromodpy.results.catalog import SimulationCatalog

        with SimulationCatalog(benchmark_root / "project") as catalog:
            iterations_df = catalog.calibration_iterations(report.session_id)

        assessed_result = _assess_method_result_from_report(
            definition=definition,
            method_profile=method_profile,
            method_instance_name=method_instance_name,
            repeat_index=repeat_index,
            seed=seed,
            effective_method_kwargs=dict(effective_profile.method_kwargs),
            requested_evaluation_budget=evaluation_budget,
            report=report,
            iterations_df=iterations_df,
            calibration_id=calibration_id,
            calibration_path=calibration_path,
            candidate_timing_values=candidate_timing_values,
            session_prepare_time_seconds=session_prepare_time_seconds,
            output_decls=output_decls,
        )
        method_results.append(assessed_result)

    pruned_artifacts = _prune_benchmark_artifacts(
        benchmark_root=benchmark_root,
        retention=retained_mode,
    )

    benchmark = TwinCalibrationBenchmarkResult(
        definition=definition,
        benchmark_root=benchmark_root,
        simulation_config_path=simulation_config_path,
        truth_simulation_config_path=truth_simulation_config_path,
        observations_truth=observations_truth,
        observations_used=observations_used,
        method_results=tuple(method_results),
        summary_path=benchmark_root / "benchmark_summary.json",
        artifact_retention=retained_mode,
        configuration_figure=configuration_figure,
        reference_objective_path=reference_objective_path,
        pruned_artifacts=pruned_artifacts,
    )
    benchmark.summary_path.write_text(
        json.dumps(benchmark.to_mapping(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return benchmark
