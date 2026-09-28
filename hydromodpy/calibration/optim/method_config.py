"""Discriminated union for the calibration method and its options.

A file writes ``method: str`` beside a free-form ``method_options`` table
(``optimizer_kwargs`` before it was renamed). Mismatches between the two used to
surface at runtime only, in the depths of an optimizer adapter, and made TOML
authoring fragile (``method = "cma_es"`` with ``method_options = {"n_trials": 50}``
validated and crashed later).

This module exposes one ``BaseModel`` per registered optimizer and a
``CalibrationMethodConfig`` discriminated union keyed by ``method``. A
helper :func:`validate_method_kwargs` converts the
``(method, method_options)`` pair into a typed config so callers detect
unknown keys eagerly, and :func:`method_options_problem` says in one sentence
what an engine refuses, for a load-time refusal or a preflight finding.

Adding a new optimizer requires three steps:

1. Register the adapter via ``@register_optimizer("name")``.
2. Declare a config class here with ``method: Literal["name"]`` and one
   field per accepted constructor kwarg.
3. List the new class in ``CalibrationMethodConfig``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

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


class BisectionMethodConfig(BaseModel):
    """Configuration for the one-dimensional root search."""

    model_config = _MODEL_CONFIG

    method: Literal["bisection"] = "bisection"
    rel_tol: float = Field(
        default=0.01,
        gt=0.0,
        description="Relative width of the bracket at which the search stops, on the "
        "calibrated parameter. The paper's one per cent. The criterion is never the "
        "size of the residual: it steps over zero and would never get small enough.",
    )
    signed_component: str = Field(
        default="J_signed",
        description="Name of the component carrying the signed residual whose sign "
        "the search brackets. Left at 'J_signed', a network output scored on two bounds "
        "is searched on J_signed_minimal and J_signed_maximal, one root each, and the "
        "value returned is their weighted geometric mean. Any other name is one root.",
    )
    sweep_points: int = Field(
        default=7,
        ge=0,
        description="Points of the coarse log sweep run before the bisection. It "
        "checks the monotonicity the paper assumes instead of supposing it, sees every "
        "crossing, and produces the crossing curves for free. Zero gives the pure "
        "bisection of the paper.",
    )
    bracket_expand: int = Field(
        default=4,
        ge=0,
        description="How many times the interval may be widened by one decade when no "
        "sign change is found. Beyond that the search raises rather than returning the "
        "better of the two ends.",
    )


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
    BisectionMethodConfig
    | GridMethodConfig
    | RandomSearchMethodConfig
    | ScipyDEMethodConfig
    | ScipyNelderMeadMethodConfig
    | CmaEsMethodConfig
    | OptunaMethodConfig
    | GPMappingMethodConfig
    | DaMhGpMethodConfig,
    Field(discriminator="method", description="Calibration method discriminator."),
]
"""Discriminated union of calibration method configs, keyed by ``method``."""


_METHOD_CONFIG_ADAPTER: TypeAdapter[CalibrationMethodConfig] = TypeAdapter(CalibrationMethodConfig)


def validate_method_kwargs(
    method: str,
    method_options: Mapping[str, Any] | None,
) -> CalibrationMethodConfig:
    """Validate ``(method, method_options)`` against the discriminated union.

    Raises :class:`pydantic.ValidationError` when ``method`` is unknown or
    when ``method_options`` carries keys foreign to that optimizer.
    """
    payload: dict[str, Any] = {"method": method}
    if method_options:
        payload.update(method_options)
    return _METHOD_CONFIG_ADAPTER.validate_python(payload)


_MODELS_BY_METHOD: dict[str, type[BaseModel]] = {
    member.model_fields["method"].default: member
    for member in get_args(get_args(CalibrationMethodConfig)[0])
}


def typed_methods() -> frozenset[str]:
    """Return the methods this module carries a model for.

    An engine registered by a plugin may have none. Its options are then left to
    its own constructor, which is the only one that knows them.
    """
    return frozenset(_MODELS_BY_METHOD)


def method_options_problem(method: str, method_options: Mapping[str, Any] | None) -> str | None:
    """Return why ``method`` refuses ``method_options``, or ``None`` when it takes them.

    The sentence names the keys the engine does not know and lists the ones it
    does, so the reader can fix the file without opening this module. ``None``
    too for a method this module has no model for.
    """
    model = _MODELS_BY_METHOD.get(str(method))
    if model is None:
        return None
    try:
        validate_method_kwargs(str(method), method_options)
    except ValidationError as exc:
        unknown = sorted(
            str(error["loc"][-1]) for error in exc.errors() if error["type"] == "extra_forbidden"
        )
        wrong = [
            f"{error['loc'][-1]} = {error['input']!r} ({error['msg']})"
            for error in exc.errors()
            if error["type"] != "extra_forbidden" and error["loc"]
        ]
        accepted = sorted(name for name in model.model_fields if name != "method")
        parts: list[str] = []
        if unknown:
            known = ", ".join(accepted) if accepted else "none"
            parts.append(
                f"{method!r} does not take {', '.join(unknown)}; the options it takes are: {known}"
            )
        if wrong:
            parts.append(f"{method!r} refuses {'; '.join(wrong)}")
        return ". ".join(parts) + "." if parts else str(exc)
    return None


def method_options_are_its_defaults(method: str, method_options: Mapping[str, Any]) -> bool:
    """Say whether ``method_options`` only write out what ``method`` does anyway.

    ``sweep_points = 7`` beside a bisection whose default is seven changes
    nothing. ``False`` for a method this module has no model for, and for
    options it refuses: nothing to compare them with.
    """
    model = _MODELS_BY_METHOD.get(str(method))
    if model is None:
        return False
    try:
        written = validate_method_kwargs(str(method), method_options).model_dump()
    except ValidationError:
        return False
    return written == model().model_dump()


def default_relative_precision(method: str, method_options: Mapping[str, Any]) -> float | None:
    """Return the relative precision ``method`` stops at when a file states none.

    Only for a method whose stopping option already is a relative precision on
    the parameter, the bisection's ``rel_tol``: its default is then the number
    a file would write as ``tolerance``. ``None`` for a method that reads the
    precision as a width in its own variable, which has no such number, and when
    ``method_options`` already sets that option.
    """
    from hydromodpy.calibration.optim.optimizer import engine_traits

    model = _MODELS_BY_METHOD.get(str(method))
    traits = engine_traits(str(method))
    option = traits.tolerance_option
    if model is None or option is None or traits.tolerance_reads != "relative_value":
        return None
    if option in method_options:
        return None
    value = model().model_dump().get(option)
    return float(value) if value is not None else None


__all__ = [
    "BisectionMethodConfig",
    "GridMethodConfig",
    "RandomSearchMethodConfig",
    "ScipyDEMethodConfig",
    "ScipyNelderMeadMethodConfig",
    "CmaEsMethodConfig",
    "OptunaMethodConfig",
    "GPMappingMethodConfig",
    "DaMhGpMethodConfig",
    "CalibrationMethodConfig",
    "default_relative_precision",
    "method_options_are_its_defaults",
    "method_options_problem",
    "typed_methods",
    "validate_method_kwargs",
]
