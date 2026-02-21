"""Shared calibration-configuration helpers for reference-case examples."""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Mapping
import warnings

import numpy as np

from hydromodpy.calibration2.core.parameters import CalibrationParameterSet


_VECTOR_METHOD_KEYS = (
    "proposal_scale",
    "prior_mean",
    "prior_std",
    "gp_length_scale",
)

_METHOD_ALIASES = {
    "delayed_acceptance_gp_mh": "da_mh_gp",
}

_METHOD_ALLOWED_KWARGS = {
    "grid_search": {"n_per_dim", "log_scale_indices"},
    "random_search": {"n_samples", "seed", "log_scale_indices"},
    "nelder_mead": {"x0", "max_iter"},
    "simplex": {"x0", "max_iter", "max_fun", "xtol", "ftol", "disp"},
    "gp_mapping": {
        "seed",
        "n_init",
        "n_refine",
        "batch_size",
        "n_candidates",
        "kappa",
        "alpha",
        "jitter",
        "n_posterior_pool",
        "n_posterior_samples",
        "log_transform",
    },
    "da_mh_gp": {
        "sigma_noise",
        "logprior_fn",
        "prior_mean",
        "prior_std",
        "n_init",
        "n_samples",
        "burn_in",
        "thin",
        "proposal_scale",
        "proposal_cov",
        "retrain_interval",
        "gp_length_scale",
        "gp_noise",
        "full_mh_prob",
        "seed",
        "cache_decimals",
    },
}


def _canonical_method_key(method):
    """
    Normalize method key and resolve known aliases.
    """
    key = str(method).strip().lower()
    return _METHOD_ALIASES.get(key, key)


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


def normalize_format_method_kwargs(
    *,
    method,
    method_kwargs,
    parameter_names,
):
    """
    Validate and normalize method kwargs into one canonical format.

    Purpose
    -------
    TOML inputs can represent per-parameter settings in different ways.
    This helper makes them uniform before they are sent to calibration methods.

    Important distinction
    ---------------------
    `method_kwargs` are algorithm settings (not model parameter values).
    Some settings are per calibration dimension (for example `proposal_scale`,
    `prior_mean`, `prior_std`, `gp_length_scale`). For these,
    `parameter_names` only defines axis order.

    For full-model calibration, these per-parameter kwargs must be:
    1) a scalar, or
    2) a mapping `{parameter_name: value}`.

    Validation/normalization performed
    ----------------------------------
    - Reject unknown kwargs for known built-in methods.
    - Named mappings are reordered in `parameter_names` order.
    - Scalars are cast to the expected type.
    - Only DA-MH GP per-parameter keys are normalized here:
      `proposal_scale`, `prior_mean`, `prior_std`, `gp_length_scale`.

    Notes
    -----
    This function does not change physical parameter values. It only normalizes
    method-configuration formats (grid density, proposal scales, priors, etc.).
    """
    names = tuple(parameter_names)
    n_dim = len(names)
    # Work on a copy to avoid mutating the input dict held by caller/config.
    adapted = dict(method_kwargs)
    if n_dim == 0:
        return adapted
    method_key = _canonical_method_key(method)

    allowed_keys = _METHOD_ALLOWED_KWARGS.get(method_key)
    if allowed_keys is not None:
        unknown = [key for key in adapted if key not in allowed_keys]
        if unknown:
            unknown_txt = ", ".join(sorted(unknown))
            allowed_txt = ", ".join(sorted(allowed_keys))
            raise ValueError(
                f"Unsupported kwargs for method '{method_key}': {unknown_txt}. "
                f"Allowed keys: {allowed_txt}"
            )

    def _normalize_numeric_values(value, value_name, cast):
        # Case C: explicit per-parameter mapping.
        # Example: {a = 0.05, Kq = 0.5, Ks = 5.0}
        if isinstance(value, Mapping):
            provided_keys = tuple(str(k) for k in value.keys())
            missing = [name for name in names if name not in value]
            extra = [key for key in provided_keys if key not in names]
            if missing or extra:
                details = []
                if missing:
                    details.append(f"missing={missing}")
                if extra:
                    details.append(f"extra={extra}")
                details_txt = ", ".join(details)
                raise ValueError(
                    f"{value_name} mapping keys must match model parameters "
                    f"{names}. Problem: {details_txt}"
                )
            return [cast(value[name]) for name in names]

        # Convert scalar-like input into a numeric array.
        arr = np.asarray(value, dtype=float).ravel()
        # Case A: scalar -> single typed value.
        if arr.size == 1:
            return cast(arr[0])
        # Positional vectors are intentionally rejected to avoid order ambiguity.
        raise ValueError(
            f"{value_name} must be a scalar or a mapping keyed by model "
            f"parameters {names}."
        )

    # Method-specific per-parameter keys for delayed-acceptance GP-MH.
    if method_key == "da_mh_gp":
        for key in _VECTOR_METHOD_KEYS:
            if key in adapted:
                adapted[key] = _normalize_numeric_values(adapted[key], key, float)

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
    - parameter_set
    - method_kwargs (normalized in full model parameter order)
    """
    calibration_cfg = config["calibration"]
    method_cfg = config.get(method_section, {})
    model_order = tuple(str(name) for name in model_parameter_order)

    objective_metric = str(calibration_cfg.get("objective_metric", objective_default))
    method = str(calibration_cfg.get(method_key, method_default))
    method_canonical = _canonical_method_key(method)
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
            "[bounds] must define all model parameters in "
            f"{model_order}. Problem: {details_txt}"
        )

    if config.get("fixed_parameters", {}):
        raise ValueError(
            "[fixed_parameters] is not supported: full-model calibration is enforced."
        )

    if method_canonical == "da_mh_gp":
        metric_key = objective_metric.strip().lower()
        if metric_key != "rmse":
            warnings.warn(
                "For method 'da_mh_gp', objective_metric is forced to 'rmse' "
                "because the likelihood is defined from RMSE(theta).",
                UserWarning,
                stacklevel=2,
            )
            objective_metric = "rmse"

    parameter_set = CalibrationParameterSet.from_bounds(
        bounds_raw,
        parameter_names=model_order,
    )
    parameter_names = parameter_set.names
    bounds = parameter_set.as_bounds_dict()
    method_kwargs_raw = {}
    if method in method_cfg:
        method_kwargs_raw = dict(method_cfg.get(method, {}))
    elif method_canonical in method_cfg:
        method_kwargs_raw = dict(method_cfg.get(method_canonical, {}))

    method_kwargs = normalize_format_method_kwargs(
        method=method_canonical,
        method_kwargs=method_kwargs_raw,
        parameter_names=parameter_names,
    )
    return {
        "objective_metric": objective_metric,
        "method": method_canonical,
        "bounds": bounds,
        "parameter_names": parameter_names,
        "parameter_set": parameter_set,
        "method_kwargs": method_kwargs,
    }
