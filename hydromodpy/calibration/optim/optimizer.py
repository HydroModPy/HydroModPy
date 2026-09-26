"""Optimizer Protocol and registry.

An optimizer proposes parameter points (``ask``) and ingests evaluation
results (``tell``). Adapters for scipy, optuna, grid-search are found under
``hydromodpy/calibration/optim/adapters/`` and registered here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

FAILED_EVAL_COST: float = 1e12
"""Sentinel cost used when an evaluation fails or returns NaN.

A large finite penalty propagates safely through CMA-ES, scipy and DA-MH-GP
adapters; NaN would poison their internal updates.
"""


@dataclass(frozen=True, slots=True)
class ParamSuggestion:
    """Candidate parameter point proposed by an optimizer.

    ``values`` maps calibrated parameter names to physical values, not
    transformed coordinates. ``trial_id`` is stable within one optimizer run
    and is used to join suggestions, evaluations, and persisted iterations.
    """

    trial_id: int
    values: Mapping[str, float]
    source: str = "ask"


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Objective result produced after evaluating one suggestion.

    The result stores the scalar minimization cost, the optional simulation id,
    execution status, timing, component diagnostics, cache provenance, and any
    backend-specific metadata needed for reports.
    """

    trial_id: int
    sim_id: str | None
    objective_value: float
    status: str = "completed"
    duration_s: float = 0.0
    components: Mapping[str, float] | None = None
    from_cache: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)


@runtime_checkable
class Optimizer(Protocol):
    """Ask/tell Protocol implemented by optimizer adapters.

    ``ask`` proposes one or more parameter points. ``tell`` feeds completed
    evaluations back to the optimizer. ``best`` and ``converged`` expose the
    state needed by ``CalibrationEngine``.
    """

    name: str

    def ask(self, n: int = 1) -> list[ParamSuggestion]: ...

    def tell(self, results: list[EvaluationResult]) -> None: ...

    def suggest_next(self) -> ParamSuggestion: ...

    def best(self) -> EvaluationResult | None: ...

    def converged(self) -> bool: ...


_BUILTIN: dict[str, Callable[..., Optimizer]] = {}


def register_optimizer(name: str) -> Callable[[type], type]:
    """Register a built-in optimizer adapter under a public method name.

    Adapter modules call this decorator at import time. The registered name is
    the value accepted by ``CalibrationConfig.method`` and ``build_optimizer``.
    """

    def deco(cls: type) -> type:
        _BUILTIN[name] = cls
        return cls

    return deco


@dataclass(frozen=True)
class EngineTraits:
    """What a search engine can and cannot be handed.

    An engine refuses an impossible pairing in its constructor, which is right
    but late: a staged calibration builds phase two's optimizer only when phase
    two starts, after phase one has spent its whole solve budget. Declaring the
    same facts here lets a check read them before anything solves.

    The defaults are permissive on purpose: an engine that constrains nothing
    declares nothing, and one that says nothing is taken at its word rather
    than assumed to be limited.
    """

    max_parameters: int | None = None
    """How many parameters the engine can move at once. ``None`` means any number."""

    required_transform: str | None = None
    """The sampling transform the engine's stopping rule is written in."""

    needs_signed_residual: bool = False
    """Whether the engine reads a signed residual the criterion has to publish."""

    supports_parallel: bool = True
    """Whether several trials of one batch can be evaluated at once."""

    tolerance_option: str | None = None
    """Name of this engine's own option that a user-level precision writes.

    ``None`` says the engine has no parameter-side stopping rule at all, and a
    declared precision is then refused rather than quietly dropped: a search that
    stops on its budget cannot honour a precision, and saying so is the only
    honest answer."""

    accepts_a_start_point: bool = False
    """Whether the engine can be told where to begin, in transformed space.

    Only two do, and it is what a restart-based uncertainty needs: repeating a
    search that always begins at the same point returns the same answer, so the
    spread it would report would be zero by construction."""

    restarts_explore_differently: bool = True
    """Whether repeating this engine can land anywhere else.

    Permissive by default, like every trait here: a stochastic sampler explores
    differently on a new seed and says nothing. An exhaustive sweep and a root
    search declare ``False``, because repeating them is the same computation twice
    and reporting its spread as an uncertainty would be a lie about a certainty."""

    tolerance_reads: Literal["search_width", "relative_value"] | None = None
    """How that option reads its number. ``search_width`` is an absolute width in
    the space the search walks, so the precision is converted into that space.
    ``relative_value`` is already a relative width on the parameter's own value,
    so the number passes through."""


DEFAULT_ENGINE_TRAITS = EngineTraits()


def engine_traits(name: str) -> EngineTraits:
    """Return what the engine registered under ``name`` declares about itself."""
    _ensure_builtins_loaded()
    engine = _BUILTIN.get(name)
    declared = getattr(engine, "traits", None)
    return declared if isinstance(declared, EngineTraits) else DEFAULT_ENGINE_TRAITS


@dataclass(frozen=True, slots=True)
class MethodChoice:
    """The search method a search that names none runs, and why."""

    method: str
    reason: str


CHOSEN_FROM: tuple[str, ...] = ("bisection", "scipy_nelder_mead")
"""The engines a search that names no method is given, in the order tried.

The first whose traits the search meets runs it. The root search comes first,
because its traits are the ones a search can miss. The minimiser declares
nothing to meet, so every search gets one, and SciPy is installed by default.
"""


def choose_method(transforms: Mapping[str, str], criteria: Iterable[str]) -> MethodChoice:
    """Return the search method of a search that names none, and why.

    ``transforms`` maps each parameter the search moves to its transform.
    ``criteria`` names the criterion of each objective block it scores.

    Each engine of :data:`CHOSEN_FROM` is faced with its ``EngineTraits``, as
    ``hmp calibrate --check`` faces a written method. The root search needs
    ``max_parameters`` at most, each in ``required_transform``, and, since it
    ``needs_signed_residual``, a signed criterion on every block
    (``CriterionRequirements.signed``): only then is the cost the absolute value
    of the residual its bracket closes on, and the answer is the crossing, not a
    minimum. One unsigned block makes the cost one to minimise.

    An unknown criterion counts as unsigned. It cannot come from a validated
    configuration, whose metrics are ``MetricKind`` literals.
    """
    from hydromodpy.calibration.criteria.registry import criterion_for

    def is_signed(name: str) -> bool:
        try:
            return criterion_for(name).requirements().signed
        except ValueError:
            # Defensive: a metric is a MetricKind literal once validated, so every
            # name a configuration hands here is registered.
            return False

    names = list(criteria)
    signed = bool(names) and all(is_signed(name) for name in names)
    lacking = ""
    for method in CHOSEN_FROM:
        traits = engine_traits(method)
        unmet = _unmet(traits, transforms, signed=signed)
        if unmet is None:
            return MethodChoice(method, _why(traits, transforms, lacking=lacking))
        lacking = lacking or unmet
    # The last engine declares nothing to meet, so this is reached only when
    # someone gives it a constraint. Its own refusal then names what is wrong.
    return MethodChoice(CHOSEN_FROM[-1], _why(DEFAULT_ENGINE_TRAITS, transforms, lacking=lacking))


def _unmet(traits: EngineTraits, transforms: Mapping[str, str], *, signed: bool) -> str | None:
    """Return what a search lacks to meet an engine's traits, or None when it meets them.

    The phrase opens the reason the next engine gives. An unsigned criterion
    needs none: "cost to minimise" already says it.
    """
    if traits.needs_signed_residual and not signed:
        return ""
    criterion = "signed criterion" if signed else "criterion"
    count = len(transforms)
    if traits.max_parameters is not None and not 0 < count <= traits.max_parameters:
        return f"{criterion} on {count} parameters"
    wanted = traits.required_transform
    other = sorted(
        name for name, transform in transforms.items() if wanted not in (None, transform)
    )
    if other:
        return f"{criterion}, {', '.join(other)} not in {wanted} space"
    return None


def _why(traits: EngineTraits, transforms: Mapping[str, str], *, lacking: str) -> str:
    """Return the reason an engine was chosen, in the words ``--list-phases`` prints."""
    if not traits.needs_signed_residual:
        return f"{lacking}, cost to minimise" if lacking else "cost to minimise"
    count = len(transforms)
    moved = "one" if count == 1 else str(count)
    where = f" {traits.required_transform}" if traits.required_transform else ""
    return f"{moved}{where} parameter{'' if count == 1 else 's'}, signed criterion"


def build_optimizer(name: str, space, **kwargs) -> Optimizer:
    """Construct a built-in optimizer by name."""
    # Lazy-load adapters so missing optionals do not break import.
    _ensure_builtins_loaded()
    if name in _BUILTIN:
        return _BUILTIN[name](space, **kwargs)
    raise KeyError(f"Unknown optimizer: {name!r}. Available built-ins: {sorted(_BUILTIN)}")


def available_optimizers() -> tuple[str, ...]:
    """Return the names of the built-in optimizers."""
    _ensure_builtins_loaded()
    return tuple(sorted(_BUILTIN))


_LOADED = False


def _ensure_builtins_loaded() -> None:
    """Auto-discover every adapter module under ``calibration/optim/adapters/``.

    Each adapter registers itself via ``@register_optimizer`` at import
    time. Optional dependencies (optuna, GP, DA-MH-GP) surface as
    ``ImportError``; those adapters just stay unregistered.
    """
    global _LOADED
    if _LOADED:
        return

    import importlib
    import pkgutil

    from hydromodpy.calibration.optim import adapters
    from hydromodpy.core.logging import get_logger

    logger = get_logger(__name__)
    for module_info in pkgutil.iter_modules(adapters.__path__):
        name = module_info.name
        if name.startswith("_"):
            continue
        try:
            importlib.import_module(f"{adapters.__name__}.{name}")
        except ImportError as exc:
            logger.debug("Optional optimizer adapter %r skipped: %s", name, exc)

    _LOADED = True
