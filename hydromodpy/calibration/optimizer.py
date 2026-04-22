"""Optimizer Protocol and registry.

An optimizer proposes parameter points (``ask``) and ingests evaluation
results (``tell``). Adapters for scipy, optuna, grid-search are found under
``hydromodpy/calibration/adapters/`` and registered here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Callable, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ParamSuggestion:
    """A candidate parameter point proposed by an optimizer."""

    trial_id: int
    values: Mapping[str, float]
    source: str = "ask"


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Outcome of evaluating one suggestion."""

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
    """Ask/tell Protocol that every optimizer adapter implements."""

    name: str

    def ask(self, n: int = 1) -> list[ParamSuggestion]: ...

    def tell(self, results: list[EvaluationResult]) -> None: ...

    def suggest_next(self) -> ParamSuggestion: ...

    def best(self) -> EvaluationResult | None: ...

    def converged(self) -> bool: ...


_BUILTIN: dict[str, Callable[..., Optimizer]] = {}


def register_optimizer(name: str) -> Callable[[type], type]:
    """Decorator to register a built-in optimizer under ``name``."""

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


_LOADED = False


def _ensure_builtins_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    # Importing these modules triggers the @register_optimizer decorators.
    from hydromodpy.calibration.adapters import grid_adapter  # noqa: F401
    from hydromodpy.calibration.adapters import scipy_adapter  # noqa: F401

    try:
        from hydromodpy.calibration.adapters import optuna_adapter  # noqa: F401
    except ImportError:
        pass

    _LOADED = True
