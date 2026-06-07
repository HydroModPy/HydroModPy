"""Optimizer Protocol and registry.

An optimizer proposes parameter points (``ask``) and ingests evaluation
results (``tell``). Adapters for scipy, optuna, grid-search are found under
``hydromodpy/calibration/adapters/`` and registered here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Protocol, runtime_checkable

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


def build_optimizer(name: str, space, **kwargs) -> Optimizer:
    """Construct an optimizer by name.

    Looks up built-ins first, then ``hydromodpy.optimizer`` entry points.
    """
    # Lazy-load adapters so missing optionals do not break import.
    _ensure_builtins_loaded()
    if name in _BUILTIN:
        return _BUILTIN[name](space, **kwargs)
    for ep in entry_points(group="hydromodpy.optimizer"):
        if ep.name == name:
            return ep.load()(space, **kwargs)
    raise KeyError(f"Unknown optimizer: {name!r}. Available built-ins: {sorted(_BUILTIN)}")


def available_optimizers() -> tuple[str, ...]:
    """Return registered optimizer names, including installed entry points."""
    _ensure_builtins_loaded()
    names = set(_BUILTIN)
    names.update(ep.name for ep in entry_points(group="hydromodpy.optimizer"))
    return tuple(sorted(names))


_LOADED = False


def _ensure_builtins_loaded() -> None:
    """Auto-discover every adapter module under ``calibration/adapters/``.

    Each adapter registers itself via ``@register_optimizer`` at import
    time. Optional dependencies (optuna, GP, DA-MH-GP) surface as
    ``ImportError``; those adapters just stay unregistered.
    """
    global _LOADED
    if _LOADED:
        return

    import importlib
    import pkgutil

    from hydromodpy.calibration import adapters
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
