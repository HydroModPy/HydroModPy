"""Shared state primitives reused by the calibration runners.

The functions in this module deal with the out-of-loop concerns: the params
hash cache preloaded from the journals of the project, the input-file
fingerprints that enter the params hash context, and the helpers that turn a
TOML calibration declaration into a runtime :class:`ParameterSpace`.
"""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.cache import ParamsHashCache
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.core.code_fingerprint import code_fingerprint
from hydromodpy.core.exceptions import StorageError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.tracking import collect_input_files
from hydromodpy.results.metric_rule import METRIC_RULE_VERSION
from hydromodpy.results.session.descriptor import list_session_dirs
from hydromodpy.results.session.journal import read_trials
from hydromodpy.results.storage.digests import sha256_directory, sha256_streaming

if TYPE_CHECKING:
    from hydromodpy.calibration.runners.trial import TrialContext, TrialMetricFn

logger = get_logger(__name__)


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


def preload_hash_cache(project_root: Path, cache: ParamsHashCache) -> int:
    """Populate ``cache`` from the trial journals of every session of the project.

    A completed trial with a scoped params hash (``v2:`` prefix) is a point
    already solved: a search of the same project that proposes it again reads
    its cost from the cache, and only the numbers of that cost: the run it may
    have become belongs to its own session. The hash embeds the fingerprint of the
    code and of the model, so a trial of other code or another model never matches.
    """
    n_before = len(cache)
    unreadable: list[str] = []
    for session_dir in list_session_dirs(project_root):
        try:
            lines = read_trials(session_dir)
        except (StorageError, ValueError) as exc:
            # A journal this build cannot read holds no cost it can trust: the
            # points it solved are solved again, and the search goes on.
            unreadable.append(f"{session_dir.name} ({type(exc).__name__})")
            continue
        for line in lines:
            for case in line.cases.values():
                params_hash = case.params_hash
                if (
                    not params_hash
                    or not params_hash.startswith("v2:")
                    or case.status != "completed"
                    or case.cost is None
                    # A trial that kept no components cannot answer a root search.
                    or not case.components
                ):
                    continue
                cache.put(
                    str(params_hash),
                    cost=float(case.cost),
                    status="completed",
                    components=dict(case.components) or None,
                )
    if unreadable:
        logger.warning(
            "The trial cache skips %d session journal(s) this version cannot read, so "
            "their points are solved again: %s.",
            len(unreadable),
            ", ".join(unreadable),
        )
    added = len(cache) - n_before
    if added:
        logger.info(
            "Preloaded %d params_hash cache entries from the sessions of the project; "
            "matching trials will be reused without re-solving.",
            added,
        )
    return added


def mesh_fingerprint(ctx: Any) -> dict[str, object] | None:
    """Return an identity for the mesh this run actually built, or ``None``.

    Declaring the requested mesh settings would not be enough: gmsh is not
    reproducible, so the same request can produce a different triangulation, and
    the stream-network criterion is normalized by cell size. A cost computed on
    another mesh is therefore not the same number, and a cache that cannot tell
    the two apart serves the first one's objectives for the second one's model.

    ``None`` when there is no mesh, which is the honest answer for a lumped model:
    keying on a placeholder would claim an identity that does not exist.
    """

    cell_mesh = getattr(getattr(ctx, "setup", None), "cell_mesh", None)
    if cell_mesh is None:
        return None
    centroids = np.asarray(cell_mesh.centers, dtype=float)
    if centroids.ndim != 2 or centroids.shape[0] == 0:
        return None
    # Rounded before hashing so a re-read of the same mesh through a different
    # float path stays the same mesh, and ordered as given because cell order IS
    # the solver's indexing.
    digest = hashlib.sha256(np.round(centroids, 6).tobytes()).hexdigest()[:32]
    return {
        "n_cells": int(centroids.shape[0]),
        "centroid_digest": digest,
        "structured": cell_mesh.structured_shape is not None,
    }


_COST_KEYS = (
    "outputs",
    "objective_blocks",
    "objective",
    "variable",
    "window",
    "validation_window",
    "aggregate",
    "reject_water_budget_above",
    "forward_model",
)
"""The keys of ``[calibration]`` that change the cost of a trial at given values.

What a trial is scored on (the outputs, the blocks, the single series), over
which samples (the window, the warm-up, the fewest paired samples), what makes
it count (the water-balance rejection) and what produces the series (the forward
model). The validation window moves no cost and is here all the same: a trial cached
under another one carries the score of those other dates. The evaluator is added on its
own, resolved, when it is not the default."""


def build_cache_context(
    *,
    cfg: CalibrationConfig,
    trial_ctx: TrialContext | None,
    space: ParameterSpace,
    override_paths: dict[str, str],
    objective_entrypoint: str | None,
) -> dict[str, object]:
    """Return the scientific context that scopes calibration cache hits.

    The key is a whitelist: what changes the cost of a trial at given parameter
    values (:data:`_COST_KEYS`), and nothing else. The method, its options, the
    seed, the precision, the budget, the bounds and the search words decide which
    values are tried, never what a tried value costs, so changing one replays
    the trials already solved. Two evaluators asked the same parameters return
    different costs, so the resolved evaluator id enters the key -- **resolved**,
    and only when it is not the default. Both halves of that sentence are
    load-bearing. Resolved, because an unset field and the default's own spelling
    name one evaluator and must not key differently. Only when it is not the
    default, because a key that appears in the payload of every document would
    move the hash of every calibration computed before this field existed,
    re-solving trials whose answer had not changed.

    ``trial_ctx`` is ``None`` when the named evaluator declares it needs no
    prepared model, and then the three members read off it -- the resolved
    configuration, the input-file fingerprints and the mesh -- describe a model
    that was never built and are left out rather than faked.

    A map file an output scores against enters by its content
    (:func:`_observed_map_digests`), since a map rewritten at the same path
    changes every network cost. Only a document that names one carries that
    member, so the hash of every other calibration stays what it was.

    The code enters by its fingerprint, one ``code.<layer>`` member per layer of
    :func:`~hydromodpy.core.code_fingerprint.code_fingerprint`, and never by the
    release number: a patch that touches no computing code keeps every hash. The
    configuration enters as it was written (``exclude_unset``): a key equal to its
    default and an absent key do not always compute the same, since a validator
    may read ``model_fields_set``. A field a later release adds moves nothing until
    a file writes it, and a default that changes moves ``code.config``.
    """
    # Direct attribute access and not getattr with a default: a TrialContext
    # always carries base_cfg, so a default here would hide its absence
    # instead of failing on it.
    base_cfg = trial_ctx.base_cfg if trial_ctx is not None else None
    model_payload: dict[str, object] = (
        base_cfg.model_dump(mode="json", exclude_unset=True) if base_cfg is not None else {}
    )
    # The project root is where the folder sits: another machine, the same cost.
    for section_name in ("calibration", "display", "overview", "mesh", "workspace"):
        model_payload.pop(section_name, None)
    # A name, a description and what is exported after the run change no cost.
    model_payload.pop("export", None)
    simulation = model_payload.get("simulation")
    if isinstance(simulation, dict):
        model_payload["simulation"] = {
            key: value for key, value in simulation.items() if key not in ("name", "description")
        }

    section = cfg.model_dump(mode="json", exclude_unset=True)
    calibration_payload = {key: section[key] for key in _COST_KEYS if key in section}

    from hydromodpy.calibration.evaluation import registry as evaluation_registry

    resolved_evaluator = evaluation_registry.resolve_id(cfg.evaluator)
    if resolved_evaluator != evaluation_registry.DEFAULT_EVALUATOR_ID:
        calibration_payload["evaluator"] = resolved_evaluator

    context: dict[str, object] = {
        "schema": "hydromodpy.calibration.params_hash.v4",
        # Code identity: a model-build or solver fix must invalidate the cache so a
        # re-run does not return pre-fix costs with zero re-solves.
        **{f"code.{layer}": digest for layer, digest in code_fingerprint().items()},
        # The session scores its window under the rule of the run: a cost from
        # another rule kept other periods and is another number.
        "metric_rule_version": METRIC_RULE_VERSION,
        "model": model_payload,
        "calibration": calibration_payload,
        "override_paths": dict(sorted(override_paths.items())),
        "parameter_space": _parameter_space_context(space),
        "input_files": _input_file_fingerprints(base_cfg) if base_cfg is not None else {},
        # The mesh that was built, not the one that was requested: gmsh is not
        # reproducible and the network criterion is normalized by cell size.
        "mesh": mesh_fingerprint(trial_ctx.ctx) if trial_ctx is not None else None,
    }

    maps = _observed_map_digests(cfg)
    if maps:
        context["observed_maps"] = maps

    if objective_entrypoint:
        context["objective_entrypoint"] = objective_entrypoint

    if trial_ctx is not None:
        domain = getattr(getattr(trial_ctx.ctx, "setup", None), "domain", None)
        domain_config = getattr(domain, "config", None)
        if domain_config is not None and hasattr(domain_config, "model_dump"):
            context["effective_domain"] = domain_config.model_dump(mode="json", exclude_unset=True)

    return context


def _parameter_space_context(space: ParameterSpace) -> list[dict[str, object]]:
    """Return the declarations of the calibrated dimensions that change a cost.

    The bounds and the two search words say where the search looks, not what a
    value costs, and the hash is taken on physical values.
    """
    payload: list[dict[str, object]] = []
    for param in space:
        payload.append(
            {
                "name": param.name,
                "path": param.path,
                "target": param.target,
                "mode": param.mode,
                "units": param.units,
            }
        )
    return payload


_SHAPEFILE_PARTS = (".shp", ".shx", ".dbf", ".prj", ".cpg")
"""The files a shapefile is read from: geometry, index, attributes, CRS, encoding."""


def _observed_map_digests(cfg: CalibrationConfig) -> dict[str, str]:
    """Return the content digest of each map file an output scores against.

    Keyed by ``<output>.map.<role>``. The paths are the ones the run reads, already
    anchored on the file that declares them.
    """
    return {f"{name}.map.{role}": _map_digest(path) for name, role, path in sorted(cfg.map_files())}


def _map_digest(path: Path) -> str:
    """Return the sha256 of a map, with its sidecars for a shapefile.

    ``"missing"`` when nothing is there: the criterion names the file it could
    not read at the first trial.
    """
    if path.is_dir():
        return sha256_directory(path)
    if not path.is_file():
        return "missing"
    if path.suffix.lower() != ".shp":
        return sha256_streaming(path)
    upper = path.suffix.isupper()
    parts = [path.with_suffix(part.upper() if upper else part) for part in _SHAPEFILE_PARTS]
    joined = ";".join(f"{part.suffix}:{sha256_streaming(part)}" for part in parts if part.is_file())
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _input_file_fingerprints(config: object) -> list[dict[str, object]]:
    """Return content fingerprints for declared input files and directories."""
    if not getattr(type(config), "model_fields", None):
        return []
    project_root = getattr(getattr(config, "workspace", None), "project_root", None)
    try:
        entries = collect_input_files(config, base=project_root)
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
            payload["sha256"] = sha256_streaming(path)
            payload["size_bytes"] = path.stat().st_size
        elif path.is_dir():
            payload["kind"] = "directory"
            payload["sha256"] = sha256_directory(path)
        else:
            payload["kind"] = "missing"
        fingerprints.append(payload)
    return sorted(fingerprints, key=lambda item: (str(item["role"]), str(item["path"])))


__all__ = [
    "space_from_config",
    "override_paths",
    "load_metric_fn_entry_point",
    "preload_hash_cache",
    "build_cache_context",
    "mesh_fingerprint",
]
