"""Discriminated union for the calibration method + optimizer kwargs.

The legacy schema accepted ``method: str`` together with a free-form
``optimizer_kwargs: dict[str, Any]``. Mismatches between the two only
surfaced at runtime, in the depths of an optimizer adapter, and made TOML
authoring fragile (``method = "cma_es"`` with ``optimizer_kwargs = {"n_trials": 50}``
silently validates and crashes later).

This module exposes one ``BaseModel`` per registered optimizer and a
``CalibrationMethodConfig`` discriminated union keyed by ``method``. A
helper :func:`validate_method_kwargs` converts the legacy
``(method, optimizer_kwargs)`` pair into a typed config so callers detect
unknown keys eagerly.

Adding a new optimizer requires three steps:

1. Register the adapter via ``@register_optimizer("name")``.
2. Declare a config class here with ``method: Literal["name"]`` and one
   field per accepted constructor kwarg.
3. List the new class in ``CalibrationMethodConfig``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

# All method configs forbid unknown keys so typos and method/kwarg
# mismatches raise at validation time instead of leaking into the adapter
# constructor where the error message is much less helpful.
_MODEL_CONFIG = ConfigDict(extra="forbid")


class GridMethodConfig(BaseModel):
    """Configuration for the deterministic ``grid`` sampler."""

    model_config = _MODEL_CONFIG

    method: Literal["grid"] = "grid"
    points_per_dim: int | list[int] | None = Field(
        default=None,
        description="Points sampled per dimension. Scalar applies to every "
        "axis; a list must match the parameter-space dimension. "
        "``None`` defaults to 5.",
    )


class RandomSearchMethodConfig(BaseModel):
    """Configuration for the ``random_search`` optimizer."""

    model_config = _MODEL_CONFIG

    method: Literal["random_search"] = "random_search"


class ScipyDEMethodConfig(BaseModel):
    """Configuration for ``scipy.optimize.differential_evolution``."""

    model_config = _MODEL_CONFIG

    method: Literal["scipy_de"] = "scipy_de"
    maxiter: int = 100
    popsize: int = 15
    tol: float = 0.01


class ScipyNelderMeadMethodConfig(BaseModel):
    """Configuration for ``scipy.optimize.minimize(method='Nelder-Mead')``."""

    model_config = _MODEL_CONFIG

    method: Literal["scipy_nelder_mead"] = "scipy_nelder_mead"
    maxiter: int | None = None
    maxfev: int | None = None
    xatol: float | None = None
    fatol: float | None = None


class CmaEsMethodConfig(BaseModel):
    """Configuration for the CMA-ES adapter."""

    model_config = _MODEL_CONFIG

    method: Literal["cma_es"] = "cma_es"
    sigma0: float = 0.25
    popsize: int = 6
    max_evaluations: int = 30
    normalize: bool = True
    restarts: int = 0


class OptunaMethodConfig(BaseModel):
    """Configuration for the Optuna adapter."""

    model_config = _MODEL_CONFIG

    method: Literal["optuna"] = "optuna"
    sampler: Literal["tpe", "random", "cmaes", "nsga"] = "tpe"
    direction: Literal["minimize", "maximize"] = "minimize"


class GPMappingMethodConfig(BaseModel):
    """Configuration for the GP-mapping (Expected Improvement) optimizer."""

    model_config = _MODEL_CONFIG

    method: Literal["gp_mapping"] = "gp_mapping"
    max_iter: int = 30
    n_init: int = 10
    ei_tol: float = 1e-6
    ei_patience: int = 3
    xi: float = 0.0
    n_restarts: int = 5
    n_refine: int | None = None
    batch_size: int = 1
    kappa: float = 0.0
    alpha: float = 1e-6
    jitter: float = 0.0


class DaMhGpMethodConfig(BaseModel):
    """Configuration for the Delayed-Acceptance MH-GP MCMC optimizer."""

    model_config = _MODEL_CONFIG

    method: Literal["da_mh_gp"] = "da_mh_gp"
    max_iter: int = 200
    burn_in: int = 20
    proposal_sigma: float | list[float] = 0.1
    n_init: int = 20
    retrain_interval: int = 10
    sigma_noise: float = 0.2
    full_mh_prob: float = 0.0
    prior_mean: float | list[float] | None = None
    prior_std: float | list[float] | None = None
    thin: int = 1
    gp_alpha: float = 1e-8
    cache_decimals: int | None = None


CalibrationMethodConfig = Annotated[
    GridMethodConfig
    | RandomSearchMethodConfig
    | ScipyDEMethodConfig
    | ScipyNelderMeadMethodConfig
    | CmaEsMethodConfig
    | OptunaMethodConfig
    | GPMappingMethodConfig
    | DaMhGpMethodConfig,
    Field(discriminator="method"),
]
"""Discriminated union of calibration method configs, keyed by ``method``."""


_METHOD_CONFIG_ADAPTER: TypeAdapter[CalibrationMethodConfig] = TypeAdapter(CalibrationMethodConfig)


def validate_method_kwargs(
    method: str,
    optimizer_kwargs: dict[str, Any] | None,
) -> CalibrationMethodConfig:
    """Validate ``(method, optimizer_kwargs)`` against the discriminated union.

    Raises :class:`pydantic.ValidationError` when ``method`` is unknown or
    when ``optimizer_kwargs`` carries keys foreign to that optimizer.
    """
    payload: dict[str, Any] = {"method": method}
    if optimizer_kwargs:
        payload.update(optimizer_kwargs)
    return _METHOD_CONFIG_ADAPTER.validate_python(payload)


__all__ = [
    "GridMethodConfig",
    "RandomSearchMethodConfig",
    "ScipyDEMethodConfig",
    "ScipyNelderMeadMethodConfig",
    "CmaEsMethodConfig",
    "OptunaMethodConfig",
    "GPMappingMethodConfig",
    "DaMhGpMethodConfig",
    "CalibrationMethodConfig",
    "validate_method_kwargs",
]
