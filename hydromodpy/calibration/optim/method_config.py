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
    """Every point of a regular grid, in the space each parameter is sampled in.

    A log parameter gets a log axis. The grid is the same whatever the seed, so
    the search is a deterministic map of the cost. Use it on one or two
    parameters, for a first look at the cost or a reference to judge another
    method against.
    """

    model_config = _MODEL_CONFIG

    method: Literal["grid"] = "grid"
    points_per_dim: int | list[int] | None = Field(
        default=None,
        description="Points sampled per dimension. Scalar applies to every "
        "axis; a list must match the parameter-space dimension. "
        "``None`` defaults to 5.",
    )


class RandomSearchMethodConfig(BaseModel):
    """Independent draws from the prior of each parameter.

    It never decides it has converged, so it runs to its budget. Use it as a
    cheap baseline to judge another method against.
    """

    model_config = _MODEL_CONFIG

    method: Literal["random_search"] = "random_search"


class LhsMethodConfig(BaseModel):
    """One Latin hypercube design, drawn before any solve and evaluated whole.

    Each stratum of each parameter is hit once. Use it for an even scan with a
    fixed budget on more parameters than a grid affords.
    """

    model_config = _MODEL_CONFIG

    method: Literal["lhs"] = "lhs"
    n_samples: int = Field(gt=0, description="Points drawn in the design. Required.")
    optimization: Literal["random-cd", "lloyd"] | None = Field(
        default=None,
        description="Post-processing passed to scipy.stats.qmc.LatinHypercube: "
        "None keeps the raw stratified draw and 'random-cd' spread the points "
        "further apart while still hitting every stratum exactly once; "
        "'lloyd' can spread points further apart too, but is a best-effort "
        "relaxation that is not guaranteed to keep the one-point-per-stratum "
        "property.",
    )


class ScipyDEMethodConfig(BaseModel):
    """Differential evolution, ``scipy.optimize.differential_evolution``.

    A population search over the whole box. It runs one trial at a time, so
    ``parallel`` buys nothing. Use it for a robust global search when trials
    cannot run side by side anyway.
    """

    model_config = _MODEL_CONFIG

    method: Literal["scipy_de"] = "scipy_de"
    maxiter: int = Field(
        default=100,
        description="Generations of the population, SciPy's maxiter. A generation "
        "costs popsize times the number of parameters evaluations.",
    )
    popsize: int = Field(
        default=15,
        description="Population size, as a multiple of the number of parameters, SciPy's popsize.",
    )
    tol: float = Field(
        default=0.01,
        description="Relative spread of the population costs at which SciPy stops, its tol.",
    )


class ScipyNelderMeadMethodConfig(BaseModel):
    """A local simplex, ``scipy.optimize.minimize(method='Nelder-Mead')``.

    It starts from the centre of the priors, or from the value an earlier
    phase passed on. It is the method a search that names none gets when its cost has
    no sign to bracket. Use it when the range is already narrow, or to refine
    the result of a coarse search.
    """

    model_config = _MODEL_CONFIG

    method: Literal["scipy_nelder_mead"] = "scipy_nelder_mead"
    maxiter: int | None = Field(
        default=None,
        description="Simplex iterations, SciPy's maxiter. None leaves SciPy's own "
        "limit; the search budget is max_iter.",
    )
    maxfev: int | None = Field(
        default=None,
        description="Evaluations, SciPy's maxfev. None leaves SciPy's own limit; the "
        "search budget is max_iter.",
    )
    xatol: float | None = Field(
        default=None,
        description="Width of the simplex at which it stops, in the space the search "
        "walks (log10 units for a log parameter). Written from calibration.tolerance; "
        "set one or the other.",
    )
    fatol: float | None = Field(
        default=None,
        description="Spread of the costs over the simplex at which it stops, SciPy's "
        "fatol. None leaves SciPy's default.",
    )


class CmaEsMethodConfig(BaseModel):
    """Covariance matrix adaptation evolution strategy, from the ``cma`` package.

    It needs the ``calibration`` extra. It can start from the value an earlier
    phase passed on. Use it on several parameters with a broad box and a cost
    with plateaus.
    """

    model_config = _MODEL_CONFIG

    method: Literal["cma_es"] = "cma_es"
    sigma0: float = Field(
        default=0.25,
        description="Initial step size, in the unit cube when normalize is true, "
        "else in the space the search walks.",
    )
    popsize: int = Field(default=6, description="Points evaluated per generation.")
    max_evaluations: int = Field(
        default=30,
        description="Evaluations the strategy may spend, restarts included.",
    )
    normalize: bool = Field(
        default=True,
        description="Rescale the box to the unit cube before the strategy runs.",
    )
    restarts: int = Field(
        default=0,
        description="Fresh strategies started from a perturbed point when one stops "
        "before the budget is spent. Zero keeps one strategy.",
    )


class BisectionMethodConfig(BaseModel):
    """A root search on one parameter: a coarse log sweep, then the bracket is halved.

    It reads a signed residual, so every block it scores must use
    ``distance_gap``, and the parameter must be searched in log space. It stops
    on the width of the bracket, never on the size of the residual. It is the
    method a search that names none gets when those conditions hold. Use it for
    the stream-network stage: one conductivity against a mapped network.
    """

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
    """An Optuna study driven trial by trial, with the TPE sampler by default.

    Use it for a first adaptive search on a few parameters. Set
    ``calibration.seed`` so a re-run proposes the same trials.
    """

    model_config = _MODEL_CONFIG

    method: Literal["optuna"] = "optuna"
    sampler: Literal["tpe", "random", "cmaes", "nsga"] = Field(
        default="tpe",
        description="Optuna sampler. 'tpe', 'random' and 'nsga' come with the base "
        "install; 'cmaes' needs the calibration extra.",
    )
    direction: Literal["minimize", "maximize"] = Field(
        default="minimize",
        description="Direction of the study. The calibration cost is always "
        "minimised, so leave it.",
    )


class GPMappingMethodConfig(BaseModel):
    """A Gaussian-process surrogate of the cost, refined where the expected improvement is highest.

    Every candidate it returns was run through the real model. It needs
    scikit-learn, which the base install carries. Use it when each run is
    expensive and the parameters are few.
    """

    model_config = _MODEL_CONFIG

    method: Literal["gp_mapping"] = "gp_mapping"
    max_iter: int = Field(
        default=30,
        description="Evaluations of the real model, the initial design included.",
    )
    n_init: int = Field(
        default=10,
        description="Random points of the initial design, drawn from the priors.",
    )
    ei_tol: float = Field(
        default=1e-6,
        description="Expected improvement under which an iteration counts as converged.",
    )
    ei_patience: int = Field(
        default=3,
        description="Iterations in a row under ei_tol before the search stops.",
    )
    xi: float = Field(
        default=0.0,
        description="Exploration margin of the expected improvement.",
    )
    n_restarts: int = Field(
        default=5,
        description="Starts of the optimiser that maximises the acquisition.",
    )
    n_refine: int | None = Field(
        default=None,
        description="Refinement rounds after the initial design. When set, the "
        "budget becomes at least n_init + n_refine * batch_size.",
    )
    batch_size: int = Field(
        default=1,
        description="Candidates proposed per refinement round.",
    )
    kappa: float = Field(
        default=0.0,
        description="When not zero, the acquisition is the lower confidence bound "
        "mu - kappa * sigma instead of the expected improvement.",
    )
    alpha: float = Field(
        default=1e-6,
        description="Noise floor of the Gaussian-process regressor.",
    )
    jitter: float = Field(
        default=0.0,
        description="Added to alpha: the nugget of the regressor is alpha + jitter.",
    )


class DaMhGpMethodConfig(BaseModel):
    """A delayed-acceptance Metropolis-Hastings chain with a Gaussian-process surrogate.

    The surrogate screens each proposal and one run of the real model corrects
    the acceptance. It reads the cost as an RMSE, with the log-likelihood
    ``-0.5 * (cost / sigma_noise)**2``, so score it on ``rmse``. The best
    candidate is the mode of the chain. It needs scikit-learn, which the base
    install carries. Use it when you want a sample of plausible values rather
    than one optimum.
    """

    model_config = _MODEL_CONFIG

    method: Literal["da_mh_gp"] = "da_mh_gp"
    max_iter: int = Field(default=200, description="Length of the chain.")
    burn_in: int = Field(
        default=20,
        description="First states of the chain left out of the sample.",
    )
    proposal_sigma: float | list[float] = Field(
        default=0.1,
        description="Standard deviation of the random-walk proposal, in the space "
        "the search walks. One number, or one per parameter.",
    )
    n_init: int = Field(
        default=20,
        description="Points of the Sobol design that trains the first surrogate.",
    )
    retrain_interval: int = Field(
        default=10,
        description="New evaluations between two fits of the surrogate.",
    )
    sigma_noise: float = Field(
        default=0.2,
        description="Scale of the likelihood, in the unit of the RMSE. Must be positive.",
    )
    full_mh_prob: float = Field(
        default=0.0,
        description="Probability, between 0 and 1, of skipping the surrogate stage for a proposal.",
    )
    prior_mean: float | list[float] | None = Field(
        default=None,
        description="Mean of a normal prior in the space the search walks. None "
        "gives a flat prior on the box.",
    )
    prior_std: float | list[float] | None = Field(
        default=None,
        description="Standard deviation of that normal prior.",
    )
    thin: int = Field(
        default=1,
        description="Keep every thin-th state of the chain after the burn-in.",
    )
    gp_alpha: float = Field(
        default=1e-8,
        description="Noise floor of the Gaussian-process regressor.",
    )
    cache_decimals: int | None = Field(
        default=None,
        description="Decimals a proposal is rounded to before it is looked up among "
        "the runs already done. None turns the lookup off.",
    )


CalibrationMethodConfig = Annotated[
    BisectionMethodConfig
    | GridMethodConfig
    | RandomSearchMethodConfig
    | LhsMethodConfig
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
