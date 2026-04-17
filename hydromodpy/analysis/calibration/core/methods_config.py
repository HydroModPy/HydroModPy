"""
Pydantic schemas for method-specific calibration kwargs.

Design goals
------------
- Keep method configuration strict and explicit.
- Validate TOML payloads before expensive calibration starts.
- Normalize flexible user syntax into a canonical runtime format.

Pydantic flow in this module
----------------------------
1) Select a schema class from `METHOD_KWARGS_MODELS`.
2) Parse and validate with `model_validate(...)`.
3) Export plain Python values with `model_dump(...)`.
4) Apply final normalization for DA-MH per-parameter settings.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


Numeric = float | int
NamedNumericMapping = dict[str, Numeric]
VectorLike = Numeric | list[Numeric] | tuple[Numeric, ...] | NamedNumericMapping


def canonical_method_name(method: str) -> str:
    """Normalize a method name (strict canonical naming, no aliasing)."""
    return str(method).strip().lower()


def _iter_numeric_values(value: VectorLike):
    """Iterate numeric values from scalar/vector/mapping formats."""
    if isinstance(value, Mapping):
        iterable = value.values()
    elif isinstance(value, (list, tuple)):
        iterable = value
    else:
        iterable = (value,)
    for item in iterable:
        yield float(item)


class _MethodKwargsBase(BaseModel):
    """
    Base class for strict method kwargs parsing.

    `extra="forbid"` means unknown keys are rejected, which avoids silent
    misconfiguration due to TOML typos.
    """

    model_config = ConfigDict(extra="forbid")


class GridSearchKwargs(_MethodKwargsBase):
    """Schema for `[calibration_method.grid_search]`."""

    n_per_dim: int | list[int]
    log_scale_indices: list[int] = Field(default_factory=list)

    # Field validators run after basic type coercion and must return the final
    # normalized value for the field.
    @field_validator("log_scale_indices")
    @classmethod
    def _validate_log_scale_indices(cls, values):
        for index in values:
            if int(index) < 0:
                raise ValueError("log_scale_indices must contain non-negative integers")
        return [int(v) for v in values]

    @field_validator("n_per_dim")
    @classmethod
    def _validate_n_per_dim(cls, value):
        if isinstance(value, int):
            if value <= 0:
                raise ValueError("n_per_dim must be > 0")
            return int(value)
        if len(value) == 0:
            raise ValueError("n_per_dim vector cannot be empty")
        out = [int(v) for v in value]
        if any(v <= 0 for v in out):
            raise ValueError("n_per_dim values must be > 0")
        return out


class RandomSearchKwargs(_MethodKwargsBase):
    """Schema for `[calibration_method.random_search]`."""

    n_samples: int
    seed: int
    log_scale_indices: list[int] = Field(default_factory=list)

    @field_validator("n_samples")
    @classmethod
    def _validate_n_samples(cls, value):
        if int(value) <= 0:
            raise ValueError("n_samples must be > 0")
        return int(value)

    @field_validator("seed")
    @classmethod
    def _validate_seed(cls, value):
        return int(value)

    @field_validator("log_scale_indices")
    @classmethod
    def _validate_log_scale_indices(cls, values):
        for index in values:
            if int(index) < 0:
                raise ValueError("log_scale_indices must contain non-negative integers")
        return [int(v) for v in values]


class CmaEsKwargs(_MethodKwargsBase):
    """Schema for `[calibration_method.cma_es]`."""

    x0: list[float] | None = None
    sigma0: float | None = None
    popsize: int | None = None
    max_iter: int | None = None
    max_evaluations: int | None = None
    seed: int | None = None
    restarts: int | None = None
    tolx: float | None = None
    tolfun: float | None = None
    normalize: bool = True
    verbose: bool = False

    @field_validator("sigma0", "tolx", "tolfun")
    @classmethod
    def _validate_positive_float_or_none(cls, value):
        if value is None:
            return None
        if float(value) <= 0.0:
            raise ValueError("value must be > 0")
        return float(value)

    @field_validator("popsize", "max_iter", "max_evaluations")
    @classmethod
    def _validate_positive_int_or_none(cls, value):
        if value is None:
            return None
        if int(value) <= 0:
            raise ValueError("value must be > 0")
        return int(value)

    @field_validator("seed")
    @classmethod
    def _validate_seed_or_none(cls, value):
        if value is None:
            return None
        return int(value)

    @field_validator("restarts")
    @classmethod
    def _validate_non_negative_int_or_none(cls, value):
        if value is None:
            return None
        if int(value) < 0:
            raise ValueError("restarts must be >= 0")
        return int(value)


class NelderMeadKwargs(_MethodKwargsBase):
    """Schema for `[calibration_method.nelder_mead]`."""

    x0: list[float] | None = None
    max_iter: int

    @field_validator("max_iter")
    @classmethod
    def _validate_max_iter(cls, value):
        if int(value) <= 0:
            raise ValueError("max_iter must be > 0")
        return int(value)


class SimplexKwargs(_MethodKwargsBase):
    """Schema for `[calibration_method.simplex]`."""

    x0: list[float] | None = None
    max_iter: int
    max_fun: int | None = None
    xtol: float | None = None
    ftol: float | None = None
    disp: bool | None = None

    @field_validator("max_iter")
    @classmethod
    def _validate_max_iter(cls, value):
        if int(value) <= 0:
            raise ValueError("max_iter must be > 0")
        return int(value)

    @field_validator("max_fun")
    @classmethod
    def _validate_max_fun(cls, value):
        if value is None:
            return None
        if int(value) <= 0:
            raise ValueError("max_fun must be > 0")
        return int(value)

    @field_validator("xtol", "ftol")
    @classmethod
    def _validate_positive_tolerances(cls, value):
        if value is None:
            return None
        if float(value) <= 0.0:
            raise ValueError("xtol/ftol must be > 0")
        return float(value)


class GpMappingKwargs(_MethodKwargsBase):
    """Schema for `[calibration_method.gp_mapping]`."""

    seed: int
    n_init: int
    n_refine: int
    batch_size: int
    n_candidates: int
    kappa: float
    alpha: float
    jitter: float
    n_posterior_pool: int
    n_posterior_samples: int
    log_transform: bool

    @field_validator("seed")
    @classmethod
    def _validate_seed(cls, value):
        return int(value)

    @field_validator(
        "n_init",
        "batch_size",
        "n_candidates",
        "n_posterior_pool",
        "n_posterior_samples",
    )
    @classmethod
    def _validate_positive_ints(cls, value):
        if int(value) <= 0:
            raise ValueError("value must be > 0")
        return int(value)

    @field_validator("n_refine")
    @classmethod
    def _validate_n_refine(cls, value):
        if int(value) < 0:
            raise ValueError("n_refine must be >= 0")
        return int(value)

    @field_validator("kappa")
    @classmethod
    def _validate_kappa(cls, value):
        if float(value) < 0.0:
            raise ValueError("kappa must be >= 0")
        return float(value)

    @field_validator("alpha", "jitter")
    @classmethod
    def _validate_non_negative_float(cls, value):
        if float(value) < 0.0:
            raise ValueError("alpha/jitter must be >= 0")
        return float(value)


class DaMhGpKwargs(_MethodKwargsBase):
    """
    Schema for `[calibration_method.da_mh_gp]`.

    Some fields are declared as `VectorLike` on purpose:
    - scalar: same value for all calibrated parameters
    - mapping: one value per named model parameter
    The final normalization to canonical parameter order is done later.
    """

    sigma_noise: float | None = None
    logprior_fn: Any | None = None
    prior_mean: VectorLike | None = None
    prior_std: VectorLike | None = None
    n_init: int | None = None
    n_samples: int | None = None
    burn_in: int | None = None
    thin: int | None = None
    proposal_scale: VectorLike | None = None
    proposal_cov: list[list[float]] | None = None
    retrain_interval: int | None = None
    gp_length_scale: VectorLike | None = None
    gp_noise: float | None = None
    full_mh_prob: float | None = None
    seed: int | None = None
    cache_decimals: int | None = None

    @field_validator("sigma_noise", "gp_noise")
    @classmethod
    def _validate_positive_or_none(cls, value):
        if value is None:
            return None
        if float(value) <= 0.0:
            raise ValueError("sigma_noise/gp_noise must be > 0")
        return float(value)

    @field_validator("n_init", "n_samples", "thin", "retrain_interval")
    @classmethod
    def _validate_positive_int_or_none(cls, value):
        if value is None:
            return None
        if int(value) <= 0:
            raise ValueError("value must be > 0")
        return int(value)

    @field_validator("burn_in", "cache_decimals")
    @classmethod
    def _validate_non_negative_int_or_none(cls, value):
        if value is None:
            return None
        if int(value) < 0:
            raise ValueError("value must be >= 0")
        return int(value)

    @field_validator("seed")
    @classmethod
    def _validate_seed_or_none(cls, value):
        if value is None:
            return None
        return int(value)

    @field_validator("full_mh_prob")
    @classmethod
    def _validate_full_mh_prob(cls, value):
        if value is None:
            return None
        out = float(value)
        if out < 0.0 or out > 1.0:
            raise ValueError("full_mh_prob must be in [0, 1]")
        return out

    @field_validator("proposal_cov")
    @classmethod
    def _validate_proposal_cov(cls, value):
        if value is None:
            return None
        arr = np.asarray(value, dtype=float)
        if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
            raise ValueError("proposal_cov must be a square 2D matrix")
        return arr.tolist()

    @field_validator("proposal_scale", "prior_std", "gp_length_scale")
    @classmethod
    def _validate_positive_vector_like_or_none(cls, value):
        if value is None:
            return None
        if any(v <= 0.0 for v in _iter_numeric_values(value)):
            raise ValueError("values must be strictly positive")
        return value

    @field_validator("prior_mean")
    @classmethod
    def _validate_numeric_vector_like_or_none(cls, value):
        if value is None:
            return None
        # Trigger float conversion early for clearer errors.
        _ = [float(v) for v in _iter_numeric_values(value)]
        return value

    @model_validator(mode="after")
    def _validate_prior_pair(self):
        # Model-level validator: checks relation between two fields after all
        # individual field validators already ran.
        has_mean = self.prior_mean is not None
        has_std = self.prior_std is not None
        if has_mean != has_std:
            raise ValueError("prior_mean and prior_std must be provided together")
        return self


METHOD_KWARGS_MODELS = {
    "grid_search": GridSearchKwargs,
    "random_search": RandomSearchKwargs,
    "cma_es": CmaEsKwargs,
    "nelder_mead": NelderMeadKwargs,
    "simplex": SimplexKwargs,
    "gp_mapping": GpMappingKwargs,
    "da_mh_gp": DaMhGpKwargs,
}
SUPPORTED_METHOD_NAMES = tuple(sorted(METHOD_KWARGS_MODELS))

_DA_MH_GP_PER_PARAMETER_KEYS = (
    "proposal_scale",
    "prior_mean",
    "prior_std",
    "gp_length_scale",
)


def _normalize_numeric_values(value, *, value_name, parameter_names, cast):
    """
    Normalize per-parameter method settings with explicit parameter-name mapping.

    Accepted formats:
    - scalar (same value for all dimensions), or
    - mapping keyed by model parameter names.
    """
    if isinstance(value, Mapping):
        named_values = {str(k): v for k, v in value.items()}
        missing = [name for name in parameter_names if name not in named_values]
        extra = [name for name in named_values if name not in parameter_names]
        if missing or extra:
            details = []
            if missing:
                details.append(f"missing={missing}")
            if extra:
                details.append(f"extra={extra}")
            details_txt = ", ".join(details)
            raise ValueError(
                f"{value_name} mapping keys must match model parameters "
                f"{parameter_names}. Problem: {details_txt}"
            )
        # Canonical output order must match model parameter order.
        return [cast(named_values[name]) for name in parameter_names]

    arr = np.asarray(value, dtype=float).ravel()
    if arr.size == 1:
        return cast(arr[0])
    raise ValueError(
        f"{value_name} must be a scalar or a mapping keyed by model "
        f"parameters {parameter_names}."
    )


def validate_method_kwargs(method_name: str, kwargs: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    Validate one method-kwargs block and return canonical method name + kwargs.

    Only built-in methods are accepted in strict calibration TOML settings.
    """
    canonical = canonical_method_name(method_name)
    model_cls = METHOD_KWARGS_MODELS.get(canonical)
    if model_cls is None:
        supported_txt = ", ".join(SUPPORTED_METHOD_NAMES)
        raise ValueError(
            f"Unsupported calibration method '{method_name}'. "
            f"Supported methods: {supported_txt}"
        )
    # `model_validate` runs all pydantic field/model validators in the schema.
    parsed = model_cls.model_validate(dict(kwargs))
    # `model_dump` returns regular Python values for downstream code.
    return canonical, parsed.model_dump(mode="python", exclude_unset=True)


def is_supported_method(method_name: str) -> bool:
    """Return True when `method_name` is a supported built-in method."""
    return canonical_method_name(method_name) in METHOD_KWARGS_MODELS


def normalize_format_method_kwargs(
    *,
    method: str,
    method_kwargs: Mapping[str, Any],
    parameter_names,
) -> dict[str, Any]:
    """
    Validate method kwargs and normalize to canonical runtime format.

    This function validates `method_kwargs` with pydantic models, then resolves
    DA-MH per-parameter settings in model-parameter order.
    """
    canonical, validated = validate_method_kwargs(method, method_kwargs)
    names = tuple(str(name) for name in parameter_names)
    if canonical != "da_mh_gp" or len(names) == 0:
        return validated

    adapted = dict(validated)
    for key in _DA_MH_GP_PER_PARAMETER_KEYS:
        if key in adapted:
            adapted[key] = _normalize_numeric_values(
                adapted[key],
                value_name=key,
                parameter_names=names,
                cast=float,
            )
    return adapted


def validate_calibration_method_section(
    section: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Validate all `[calibration_method.<method>]` subsections."""
    if section is None:
        return {}
    if not isinstance(section, Mapping):
        raise ValueError("[calibration_method] must be a mapping")

    validated: dict[str, dict[str, Any]] = {}
    for raw_name, raw_kwargs in section.items():
        method_name = str(raw_name)
        if not isinstance(raw_kwargs, Mapping):
            raise ValueError(
                f"[calibration_method.{method_name}] must be a mapping of kwargs"
            )
        canonical, kwargs = validate_method_kwargs(method_name, raw_kwargs)
        if canonical in validated:
            raise ValueError(
                f"Duplicate method configuration key: '{method_name}' "
                f"and existing '{canonical}'"
            )
        validated[canonical] = kwargs
    return validated


def validate_calibration_method_section_or_raise(section: Mapping[str, Any] | None):
    """Validation wrapper preserving a concise ValueError API."""
    try:
        return validate_calibration_method_section(section)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
