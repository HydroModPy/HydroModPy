"""Shared state primitives reused by both calibration runners.

The functions in this module deal with the *out-of-loop* concerns:

- default ``CalibrationStore`` factory,
- params_hash cache preload from DuckDB,
- input-file fingerprinting feeding the params_hash context,
- helpers to translate a TOML calibration declaration into a runtime
  :class:`ParameterSpace`.

They are intentionally decoupled from the ask/tell loop so the CLI and
programmatic runners can share the same plumbing.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.calibration.cache import ParamsHashCache
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.parameters import ParameterSpace
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.calibration.runners.trial import TrialContext, TrialMetricFn

logger = get_logger(__name__)

CalibrationStoreFactory = Callable[[Path, object], Any]


def default_store_factory(workspace: Path, persistence: object) -> Any:
    """Open the default calibration store (project catalog DuckDB)."""
    from hydromodpy.results.catalog import Catalog

    return Catalog(workspace, persistence=persistence)


# ---------------------------------------------------------------------------
# Param space helpers
# ---------------------------------------------------------------------------


def space_from_config(cfg: CalibrationConfig) -> ParameterSpace:
    """Return a :class:`ParameterSpace` built from the calibration declarations."""
    declarations = {
        name: decl.model_dump(exclude_none=True) for name, decl in cfg.parameters.items()
    }
    return ParameterSpace.from_toml_mapping(declarations)


def override_paths(cfg: CalibrationConfig) -> dict[str, str]:
    """Return the ``{parameter_name: dotted_path}`` mapping for trial injection."""
    out: dict[str, str] = {}
    for name, decl in cfg.parameters.items():
        dotted = decl.target if decl.target is not None else decl.path
        if dotted:
            out[name] = dotted
    if not out:
        raise ValueError(
            "Calibration parameters must declare a 'path' or 'target' (e.g. "
            "'flow.param.K.field.value') so values can be injected into the "
            "simulation config."
        )
    return out


# ---------------------------------------------------------------------------
# Custom Python objective escape hatch
# ---------------------------------------------------------------------------


def load_metric_fn_entry_point(spec: str) -> TrialMetricFn:
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


def preload_hash_cache(catalog_conn, cache: ParamsHashCache) -> int:
    """Populate ``cache`` from previously-promoted calibration iterations.

    Wrapped by DuckDB's lock-retry decorator so concurrent ``hmp`` sessions on
    the same workspace do not surface ``IOException``.
    """
    from hydromodpy.core.io.db_retry import with_lock_retry

    @with_lock_retry()
    def _run() -> list[tuple[str, str | None, float, str, str | None]]:
        return catalog_conn.execute(
            """
            SELECT params_hash, sim_id, objective_value, status, metrics
              FROM calibration_iterations
             WHERE params_hash IS NOT NULL
               AND params_hash LIKE 'v2:%'
               AND status      = 'completed'
               AND objective_value IS NOT NULL
            """
        ).fetchall()

    rows = _run()
    n_before = len(cache)
    for params_hash, sim_id, objective_value, status, metrics_json in rows:
        if not params_hash:
            continue
        components = None
        if metrics_json:
            try:
                components = json.loads(metrics_json)
            except (TypeError, ValueError):
                components = None
        cache.put(
            str(params_hash),
            str(sim_id) if sim_id is not None else None,
            objective_value=float(objective_value),
            status=str(status),
            components=components,
        )
    added = len(cache) - n_before
    if added:
        # The hash embeds the code version, so entries from a different HydroModPy
        # build simply miss; still surface preloading so a cached run is not silent.
        logger.info(
            "Preloaded %d params_hash cache entries from prior calibration iterations; "
            "matching trials will be reused without re-solving.",
            added,
        )
    return added


def build_cache_context(
    *,
    cfg: CalibrationConfig,
    trial_ctx: TrialContext,
    space: ParameterSpace,
    override_paths: dict[str, str],
    objective_entrypoint: str | None,
) -> dict[str, object]:
    """Return the scientific context that scopes calibration cache hits."""
    model_payload = trial_ctx.base_cfg.model_dump(mode="json")
    model_payload.pop("calibration", None)
    model_payload.pop("display", None)
    model_payload.pop("overview", None)
    model_payload.pop("mesh_catchment", None)

    calibration_payload = cfg.model_dump(mode="json")
    for runtime_key in (
        "max_iter",
        "batch_size",
        "parallel",
        "save_runs",
        "save_best_n",
        "use_cache",
        "persistence",
        "persist_iteration_detail",
        "materialize_candidates",
        "candidates_root",
        "rerun_best_with_outputs",
    ):
        calibration_payload.pop(runtime_key, None)

    from hydromodpy.core.version import __version__ as _hmp_version

    context: dict[str, object] = {
        "schema": "hydromodpy.calibration.params_hash.v2",
        # Code identity: a model-build or solver fix must invalidate the cache so a
        # re-run does not return pre-fix objectives with zero re-solves.
        "code_version": str(_hmp_version),
        "model": model_payload,
        "calibration": calibration_payload,
        "override_paths": dict(sorted(override_paths.items())),
        "parameter_space": _parameter_space_context(space),
        "input_files": _input_file_fingerprints(trial_ctx.base_cfg),
    }

    if objective_entrypoint:
        context["objective_entrypoint"] = objective_entrypoint

    domain = getattr(getattr(trial_ctx.ctx, "setup", None), "domain", None)
    domain_config = getattr(domain, "config", None)
    if domain_config is not None and hasattr(domain_config, "model_dump"):
        context["effective_domain"] = domain_config.model_dump(mode="json")

    return context


def _parameter_space_context(space: ParameterSpace) -> list[dict[str, object]]:
    """Return serializable declarations for the calibrated dimensions."""
    payload: list[dict[str, object]] = []
    for param in space:
        payload.append(
            {
                "name": param.name,
                "bounds": [param.lower, param.upper],
                "transformed_bounds": [
                    param.lower_transformed,
                    param.upper_transformed,
                ],
                "transform": param.transform,
                "prior": param.prior,
                "path": param.path,
                "target": param.target,
                "mode": param.mode,
                "units": param.units,
            }
        )
    return payload


def _input_file_fingerprints(config: object) -> list[dict[str, object]]:
    """Return content fingerprints for declared input files and directories."""
    try:
        from hydromodpy.core.tracking import collect_input_files
    except Exception:
        return []
    if not getattr(type(config), "model_fields", None):
        return []
    try:
        entries = collect_input_files(config)
    except Exception:
        return []

    fingerprints: list[dict[str, object]] = []
    for entry in entries:
        path = entry.canonical_path
        payload: dict[str, object] = {
            "role": entry.role,
            "category": entry.category,
            "path": str(path),
            "exists": path.exists(),
        }
        if path.is_file():
            payload["kind"] = "file"
            payload["sha256"] = _sha256_file(path)
            payload["size_bytes"] = path.stat().st_size
        elif path.is_dir():
            payload["kind"] = "directory"
            payload["sha256"] = _sha256_directory(path)
        else:
            payload["kind"] = "missing"
        fingerprints.append(payload)
    return sorted(fingerprints, key=lambda item: (str(item["role"]), str(item["path"])))


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_directory(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


__all__ = [
    "CalibrationStoreFactory",
    "default_store_factory",
    "space_from_config",
    "override_paths",
    "load_metric_fn_entry_point",
    "preload_hash_cache",
    "build_cache_context",
]
