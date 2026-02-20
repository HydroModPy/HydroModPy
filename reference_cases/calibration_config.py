"""Shared calibration-configuration helpers for reference-case examples."""

from __future__ import annotations

from pathlib import Path
import tomllib

import numpy as np


_VECTOR_METHOD_KEYS = (
    "proposal_scale",
    "prior_mean",
    "prior_std",
    "gp_length_scale",
)


def parse_named_bounds(bounds_cfg, *, allowed_names=None):
    """
    Parse TOML bounds as `{name: (low, high)}` with validation.

    Parameters
    ----------
    bounds_cfg : mapping
        TOML `[bounds]` section.
    allowed_names : iterable[str] or None
        Optional whitelist of parameter names.
    """
    if not isinstance(bounds_cfg, dict) or not bounds_cfg:
        raise ValueError("[bounds] must be a non-empty mapping")

    allowed = None if allowed_names is None else set(allowed_names)
    bounds = {}
    for name, pair in bounds_cfg.items():
        key = str(name)
        if allowed is not None and key not in allowed:
            allowed_txt = ", ".join(sorted(allowed))
            raise ValueError(f"Unknown bound '{key}'. Allowed names: {allowed_txt}")
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(f"Bounds for '{key}' must be a 2-value list/tuple")
        low = float(pair[0])
        high = float(pair[1])
        if low >= high:
            raise ValueError(f"Invalid bounds for '{key}': lower must be < upper")
        bounds[key] = (low, high)

    return bounds


def adapt_method_kwargs_to_subset(
    *,
    method,
    method_kwargs,
    calibrated_parameter_names,
    model_parameter_order,
):
    """
    Adapt method-specific keyword arguments from full model dimension
    to the calibrated parameter subset dimension.

    Purpose
    -------
    In many workflows, the full model may define N parameters,
    but calibration may only involve a subset of them (dimension d ≤ N).

    Method configuration values coming from TOML (e.g. proposal_scale,
    prior_mean, n_per_dim, log_scale_indices) may therefore be specified:

    1) As a scalar → applied to all calibrated parameters.
    2) In subset dimension (length = d).
    3) In full model order (length = N).

    This function transparently converts any of these formats into
    the calibrated subset ordering.

    Parameters
    ----------
    method : str
        Name of the calibration method (e.g., "simplex", "da_mh_gp").
        Some methods require special handling for vector parameters.

    method_kwargs : dict
        Dictionary of method-specific keyword arguments (typically
        read from TOML).

    calibrated_parameter_names : sequence[str]
        Names of parameters being calibrated (subset).

    model_parameter_order : sequence[str]
        Full ordered list of model parameters.

    Returns
    -------
    dict
        A copy of `method_kwargs` where vector-like entries are
        projected onto the calibrated subset dimension.

    Examples
    --------
    Example 1 — Full model vector projected to subset

    Full model parameters:
        ["C", "k", "alpha", "beta"]

    Calibrated subset:
        ["C", "k"]

    TOML specifies:
        proposal_scale = [0.5, 0.01, 0.2, 0.3]

    After adaptation:
        proposal_scale = [0.5, 0.01]

    Only the entries corresponding to calibrated parameters are kept.

    Example 2 — Already in subset dimension

        proposal_scale = [0.5, 0.01]

    No modification is applied.

    Example 3 — Scalar value

        proposal_scale = 0.1

    Interpreted as applying uniformly to all calibrated parameters.

    Example 4 — log_scale_indices in full dimension

    Full model:
        ["C", "k", "alpha"]

    Subset:
        ["C", "k"]

    TOML:
        log_scale_indices = [0, 2]

    Index 2 corresponds to "alpha", which is not calibrated.
    After adaptation:
        log_scale_indices = [0]

    Notes
    -----
    This mechanism ensures that method configuration remains flexible:
    users can write TOML vectors either in full model dimension or
    directly in calibrated subset dimension, without changing code.

    Internally, projection is performed by mapping global indices
    (full model order) to local subset indices.
    """

    names = tuple(calibrated_parameter_names)
    model_order = tuple(model_parameter_order)
    n_dim = len(names)
    adapted = dict(method_kwargs)
    if n_dim == 0:
        return adapted

    order_index = {name: i for i, name in enumerate(model_order)}
    subset_global_idx = np.array([order_index[name] for name in names], dtype=int)

    def _subset_numeric_values(value, value_name, cast):
        arr = np.asarray(value, dtype=float).ravel()
        if arr.size == 1:
            return cast(arr[0])
        if arr.size == n_dim:
            return [cast(v) for v in arr]
        if arr.size == len(model_order):
            return [cast(v) for v in arr[subset_global_idx]]
        raise ValueError(
            f"{value_name} length must be 1, {n_dim}, or {len(model_order)} "
            f"(full model order)."
        )

    if "n_per_dim" in adapted:
        adapted["n_per_dim"] = _subset_numeric_values(adapted["n_per_dim"], "n_per_dim", int)

    if "log_scale_indices" in adapted:
        raw = [int(i) for i in adapted["log_scale_indices"]]
        if any(i < 0 for i in raw):
            raise ValueError("log_scale_indices must contain non-negative integers")
        if all(i < n_dim for i in raw):
            adapted["log_scale_indices"] = sorted(set(raw))
        else:
            global_to_local = {int(g): int(l) for l, g in enumerate(subset_global_idx)}
            adapted["log_scale_indices"] = sorted({global_to_local[i] for i in raw if i in global_to_local})

    method_key = str(method).strip().lower()
    if method_key in ("da_mh_gp", "delayed_acceptance_gp_mh"):
        for key in _VECTOR_METHOD_KEYS:
            if key in adapted:
                adapted[key] = _subset_numeric_values(adapted[key], key, float)

    return adapted


def load_calibration_toml(
    config_path,
    *,
    required_sections=("chronicle", "calibration", "bounds"),
):
    """
    Load calibration TOML and validate required top-level sections.
    """
    path = Path(config_path)
    with path.open("rb") as stream:
        config = tomllib.load(stream)

    for section in required_sections:
        if section not in config:
            raise KeyError(f"Missing [{section}] section in {path}")
    return config


def resolve_calibration_settings(
    config,
    *,
    model_parameter_order,
    objective_default="kge",
    method_default="simplex",
    method_key="global_method",
    method_section="calibration_method",
):
    """
    Resolve common calibration settings from TOML.

    Returns a dict with:
    - objective_metric
    - method
    - bounds
    - parameter_names
    - method_kwargs (adapted in model parameter order)
    """
    calibration_cfg = config["calibration"]
    method_cfg = config.get(method_section, {})
    model_order = tuple(str(name) for name in model_parameter_order)

    objective_metric = str(calibration_cfg.get("objective_metric", objective_default))
    method = str(calibration_cfg.get(method_key, method_default))
    bounds_raw = parse_named_bounds(config["bounds"], allowed_names=model_order)
    bound_names = tuple(bounds_raw.keys())

    missing = [name for name in model_order if name not in bounds_raw]
    extra = [name for name in bound_names if name not in model_order]
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing={missing}")
        if extra:
            details.append(f"extra={extra}")
        details_txt = ", ".join(details)
        raise ValueError(
            "Subset calibration is disabled: [bounds] must define all model "
            f"parameters in {model_order}. Problem: {details_txt}"
        )

    fixed_cfg = config.get("fixed_parameters", {})
    if fixed_cfg:
        raise ValueError(
            "Subset calibration is disabled: [fixed_parameters] is not supported."
        )

    parameter_names = model_order
    bounds = {name: bounds_raw[name] for name in model_order}
    method_kwargs = adapt_method_kwargs_to_subset(
        method=method,
        method_kwargs=dict(method_cfg.get(method, {})),
        calibrated_parameter_names=parameter_names,
        model_parameter_order=model_order,
    )
    return {
        "objective_metric": objective_metric,
        "method": method,
        "bounds": bounds,
        "parameter_names": parameter_names,
        "method_kwargs": method_kwargs,
    }
