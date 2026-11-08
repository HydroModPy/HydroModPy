"""Optimizer registry, on the shared plugin engine.

An optimizer proposes parameter points (``ask``) and ingests evaluation
results (``tell``). Adapters for scipy, optuna, grid-search and the rest
live under ``hydromodpy/calibration/optim/adapters/`` and join one registry,
``optimizers``, an instance of :class:`~hydromodpy.core.plugin_registry.
PluginRegistry`: an in-tree declaration imported on first lookup, then one
scan of the ``hydromodpy.calibration.optimizer`` entry-point group for what
the build does not carry. Resolve a name with ``optimizers.get(name)``,
list the ids with ``optimizers.names()``, and register a third-party class
on the same engine with ``optimizers.register(cls)``.

What used to live here and does not any more
--------------------------------------------
- The ``Optimizer`` Protocol carried a ``name`` attribute and a
  ``suggest_next`` method. The engine loop reads ``ask``, ``tell``, ``best``
  and ``converged`` on the instances, and the registry reads the id off the
  ``name`` attribute of the class, so neither is part of the port any more.
  ``suggest_next`` stays on the adapters that implement it, as an ordinary
  method outside the port's members.
- The decorator ``register_optimizer`` and the ``_BUILTIN`` dict, filled by a
  ``pkgutil`` scan of ``adapters/``, are gone: a built-in is declared by a
  dotted path in :data:`_BUILTIN_PATHS`, and a third-party one by an entry
  point of group ``hydromodpy.calibration.optimizer``. No module global
  changes while a calibration runs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from hydromodpy.core.exceptions import OptimizerError
from hydromodpy.core.plugin_registry import PluginRegistry

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
    cost: float
    status: str = "completed"
    duration_s: float = 0.0
    components: Mapping[str, float] | None = None
    from_cache: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)


@runtime_checkable
class Optimizer(Protocol):
    """Ask/tell Protocol implemented by optimizer adapters.

    The port's members are ``ask``, ``tell``, ``best`` and ``converged``:
    ``ask`` proposes one or more parameter points, ``tell`` feeds completed
    evaluations back, and ``best`` and ``converged`` expose the state needed
    by ``CalibrationEngine``. A class may carry more, such as ``suggest_next``
    on the adapters that plan their own points; the registry reads none of it
    and ``name`` is read off a class as its id, not declared here.
    """

    def ask(self, n: int = 1) -> list[ParamSuggestion]: ...

    def tell(self, results: list[EvaluationResult]) -> None: ...

    def best(self) -> EvaluationResult | None: ...

    def converged(self) -> bool: ...


def best_completed(history: Iterable[EvaluationResult]) -> EvaluationResult | None:
    """Return the completed result of lowest cost, or ``None`` when none completed."""
    return min(
        (result for result in history if result.status == "completed"),
        key=lambda result: result.cost,
        default=None,
    )


ENTRY_POINT_GROUP = "hydromodpy.calibration.optimizer"
"""The out-of-tree plugin group. One entry point per optimizer, named on its id."""

_BUILTIN_PATHS: dict[str, str] = {
    "bisection": "hydromodpy.calibration.optim.adapters.bisection_adapter:BisectionAdapter",
    "cma_es": "hydromodpy.calibration.optim.adapters.cma_adapter:CmaEsAdapter",
    "da_mh_gp": "hydromodpy.calibration.optim.adapters.da_mh_gp_adapter:DaMhGpOptimizer",
    "gp_mapping": "hydromodpy.calibration.optim.adapters.gp_mapping_adapter:GPMappingOptimizer",
    "grid": "hydromodpy.calibration.optim.adapters.grid_adapter:GridAdapter",
    "lhs": "hydromodpy.calibration.optim.adapters.lhs_adapter:LhsAdapter",
    "optuna": "hydromodpy.calibration.optim.adapters.optuna_adapter:OptunaAdapter",
    "random_search": (
        "hydromodpy.calibration.optim.adapters.random_search_adapter:RandomSearchAdapter"
    ),
    "scipy_de": "hydromodpy.calibration.optim.adapters.scipy_adapter:ScipyDE",
    "scipy_nelder_mead": ("hydromodpy.calibration.optim.adapters.scipy_adapter:ScipyNelderMead"),
}
"""Dotted paths of the adapters this build ships, imported on first lookup.

Format ``"<name>": "<module>:<Class>"``, the rule every registry of this
repository follows. The names are the public method names, and the paths are
declarations: resolving one does not import the adapter unless a calibration
builds it.
"""

optimizers = PluginRegistry(
    kind="optimizer",
    id_attributes=("name",),
    group=ENTRY_POINT_GROUP,
    builtin_paths=_BUILTIN_PATHS,
    members=lambda: ("ask", "tell", "best", "converged"),
    error=OptimizerError,
)
"""The optimizer registry: ``optimizers.get``, ``optimizers.names`` and ``optimizers.register``.

``optimizers.get(name)`` returns the constructor of the built-in under *name*,
``optimizers.names()`` the ids this build serves, in-tree declared plus the
entry points of the group after one scan, and ``optimizers.register(cls)``
places a third-party class under the id its ``name`` attribute declares.
"""


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

    required_search_space: str | None = None
    """The search space the engine's stopping rule is written in."""

    needs_signed_residual: bool = False
    """Whether the engine reads a signed residual the criterion has to publish."""

    supports_parallel: bool = True
    """Whether several trials of one batch can be evaluated at once."""

    reach: Callable[[Mapping[str, Any], int], int] | None = None
    """How many solves the engine can use at once, from its method options and the number
    of parameters. ``None`` says no limit. An engine without ``supports_parallel`` reads as 1."""

    precision_option: str | None = None
    """Name of this engine's own option that a user-level precision writes.

    ``None`` says the engine has no parameter-side stopping rule at all, and a
    declared precision is then refused rather than quietly dropped: a search that
    stops on its budget cannot honor a precision, and saying so is the only
    honest answer."""

    accepts_a_start_point: bool = False
    """Whether the engine can be told where to begin, in transformed space.

    Only two do, and it is what a restart-based uncertainty needs: repeating a
    search that always begins at the same point returns the same answer, so the
    spread it would report would be zero by construction."""

    draws_a_normal: bool = True
    """Whether the engine can draw a parameter declared with the ``normal`` sampling.

    An engine that cannot refuses it in its constructor, and the preflight reads
    this to refuse it before anything is prepared."""

    restarts_explore_differently: bool = True
    """Whether repeating this engine can land anywhere else.

    Permissive by default, like every trait here: a stochastic sampler explores
    differently on a new seed and says nothing. An exhaustive sweep and a root
    search declare ``False``, because repeating them is the same computation twice
    and reporting its spread as an uncertainty would be a lie about a certainty."""

    precision_reads: Literal["search_width", "relative_value"] | None = None
    """How that option reads its number. ``search_width`` is an absolute width in
    the space the search walks, so the precision is converted into that space.
    ``relative_value`` is already a relative width on the parameter's own value,
    so the number passes through."""

    takes_max_trials: bool = False
    """Whether the engine is built knowing the evaluations it may spend.

    The surrogate that sizes its initial design on the budget, and the strategy
    that plans its restarts on it, need the number before the first ask. The
    runner hands it the ``max_trials`` of the search (``"auto"`` resolved), so
    the budget is written once, in ``max_trials``, and never as a method option."""

    reads_cost_as: str | None = None
    """The metric the engine assumes its cost is, when it builds on the number.

    ``None`` for an engine that only compares costs. The sampler that turns the
    cost into a likelihood declares the metric that likelihood is written for,
    and a search scored on another one is warned before it runs."""

    fixed_plan: bool = False
    """Whether the engine can be asked for all that is left and hands out what is ready.

    One queue then takes the points, so no point waits for the result of another."""

    takes_width: bool = False
    """Whether the engine is built knowing the ``parallel`` of the search, as ``width``."""

    announced: bool = True
    """Whether the method is in the list the docs and the refusals print.

    ``False`` for a method that still runs when a file names it, but that
    the project does not offer yet. The default says nothing, like every trait
    here."""


DEFAULT_ENGINE_TRAITS = EngineTraits()
"""The traits of an engine that declares none: permissive in every way."""


@dataclass(frozen=True)
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


def choose_method(search_spaces: Mapping[str, str], criteria: Iterable[str]) -> MethodChoice:
    """Return the search method of a search that names none, and why.

    ``search_spaces`` maps each parameter the search moves to its search space.
    ``criteria`` names the criterion of each objective block it scores.

    Each engine of :data:`CHOSEN_FROM` is faced with its ``EngineTraits``, as
    ``hmp config check`` faces a written method. The root search needs
    ``max_parameters`` at most, each in ``required_search_space``, and, since it
    ``needs_signed_residual``, a signed criterion on every block
    (``CriterionRequirements.signed``): only then is the cost the absolute value
    of the residual its bracket closes on, and the answer is the crossing, not a
    minimum. One unsigned block makes the cost one to minimize.

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
        unmet = _unmet(traits, search_spaces, signed=signed)
        if unmet is None:
            return MethodChoice(method, _why(traits, search_spaces, lacking=lacking))
        lacking = lacking or unmet
    # The last engine declares nothing to meet, so this is reached only when
    # someone gives it a constraint. Its own refusal then names what is wrong.
    return MethodChoice(
        CHOSEN_FROM[-1], _why(DEFAULT_ENGINE_TRAITS, search_spaces, lacking=lacking)
    )


def _unmet(traits: EngineTraits, search_spaces: Mapping[str, str], *, signed: bool) -> str | None:
    """Return what a search lacks to meet an engine's traits, or None when it meets them.

    The phrase opens the reason the next engine gives. An unsigned criterion
    needs none: "cost to minimize" already says it.
    """
    if traits.needs_signed_residual and not signed:
        return ""
    criterion = "signed criterion" if signed else "criterion"
    count = len(search_spaces)
    if traits.max_parameters is not None and not 0 < count <= traits.max_parameters:
        return f"{criterion} on {count} parameters"
    wanted = traits.required_search_space
    other = sorted(name for name, space in search_spaces.items() if wanted not in (None, space))
    if other:
        return f"{criterion}, {', '.join(other)} not in {wanted} space"
    return None


def _why(traits: EngineTraits, search_spaces: Mapping[str, str], *, lacking: str) -> str:
    """Return the reason an engine was chosen, in the words ``--list-phases`` prints."""
    if not traits.needs_signed_residual:
        return f"{lacking}, cost to minimise" if lacking else "cost to minimise"
    count = len(search_spaces)
    moved = "one" if count == 1 else str(count)
    where = f" {traits.required_search_space}" if traits.required_search_space else ""
    return f"{moved}{where} parameter{'' if count == 1 else 's'}, signed criterion"


def engine_traits(name: str) -> EngineTraits:
    """Return what the engine registered under ``name`` declares about itself.

    Resolution order: the cache, the in-tree declaration imported on first
    lookup, then one scan of the entry-point group. An engine that names
    nothing is the default: permissive, so that nothing written in a file is
    quietly dropped.
    """
    engine = optimizers.get(name)
    declared = getattr(engine, "traits", None)
    return declared if isinstance(declared, EngineTraits) else DEFAULT_ENGINE_TRAITS


def build_optimizer(name: str, space, **kwargs) -> Optimizer:
    """Construct a built-in optimizer by name, from the shared registry.

    The registry returns the class and not an object: an adapter is a class
    with ``ask``, ``tell``, ``best`` and ``converged``, and its constructor
    receives everything else. An unknown name is an :class:`OptimizerError`
    naming what this build serves, in place of the ``KeyError`` a bare dict
    lookup raised, because a missing method is a calibration refusal and not a
    missing key.
    """
    try:
        cls = optimizers.get(name)
    except OptimizerError as exc:
        raise OptimizerError(
            f"Unknown optimizer: {name!r}. Available built-ins: {', '.join(optimizers.names())}"
        ) from exc
    return cls(space, **kwargs)


def announced_optimizers() -> tuple[str, ...]:
    """Return the built-in optimizers the project offers, those that declare ``announced``.

    Read on the traits, one lookup per method: an engine without a
    ``EngineTraits`` instance is read as announcing itself, like every default
    in this module.
    """
    return tuple(name for name in optimizers.names() if engine_traits(name).announced)
