"""The five states a run can start from, as frozen records in SI units.

A ``HeadRule`` is resolved by each backend on its own grid. A ``SteadyStart``
and a ``CyclicStart`` ask the backend for an auxiliary solve of the same
solver, which starts from the top. A ``PriorState`` is the last state of an
earlier run, read once before the solve. A ``SolvedState`` is the head and the
lake stages an auxiliary solve returned, set as they are.

The first window of a chain that starts from a steady or cyclic state solves
its auxiliary model over the whole simulation, so the start is the one of the
run in one piece. ``over`` carries the ``Model`` of the whole simulation for
that solve. It is typed ``Any`` because this folder reads only numpy and its
neighbours (rule 6), and the ``Model`` holds these states.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import numpy as np

HEAD_RULE_KINDS: tuple[str, ...] = ("top", "top_offset", "bottom", "custom")
"""The ``flow.ic`` kinds a backend resolves on its grid without a solve."""

_KINDS_WITH_A_VALUE = frozenset({"top_offset", "custom"})


@dataclass(frozen=True, slots=True)
class HeadRule:
    """A start head read off the grid: the top, the top minus ``value_m``, the bottom, or ``value_m``.

    ``value_m`` is in metres. It is the depth below the top for ``top_offset``
    and the head itself for ``custom``. The other kinds take no value.
    """

    kind: str
    value_m: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in HEAD_RULE_KINDS:
            raise ValueError(
                f"A head rule kind is one of {', '.join(HEAD_RULE_KINDS)}; got {self.kind!r}."
            )
        if self.kind in _KINDS_WITH_A_VALUE and self.value_m is None:
            raise ValueError(f"flow.ic.value is required when flow.ic.kind='{self.kind}'")
        if self.kind not in _KINDS_WITH_A_VALUE and self.value_m is not None:
            raise ValueError(
                "flow.ic.value is only supported when kind='custom' or kind='top_offset'"
            )


@dataclass(frozen=True)
class SteadyStateStrategy:
    """How the steady solve of ``flow.ic.kind = 'steady_state'`` is forced.

    ``source`` is ``recharge``, ``mean_recharge`` or ``prescribed``. The first
    two read the recharge chronicle through ``recharge_statistic``. The third
    holds the solve at ``rate_m_s``, in m/s, on every period.
    """

    source: str = "mean_recharge"
    recharge_statistic: str | None = "time_mean"
    boundary_condition_policy: str = "first_period"
    rate_m_s: float | None = None


@dataclass(frozen=True)
class CyclicSpinupStrategy:
    """How ``flow.ic.kind = 'spinup_cyclic'`` repeats the run's period.

    At most ``max_cycles`` cycles, settled when no head moves by more than
    ``tol_head_m`` metres between two cycles. ``first_cycle_from`` is ``top``
    or ``steady_state``.
    """

    max_cycles: int = 4
    tol_head_m: float = 0.01
    first_cycle_from: str = "top"


@dataclass(frozen=True, slots=True)
class SteadyStart:
    """Start from the steady solve of the same solver under ``strategy``.

    ``over`` is the ``Model`` of the whole simulation when this run is the
    first window of a chain, so the steady solve averages the forcings of the
    whole simulation. It is ``None`` everywhere else, and the solve averages
    the forcings of the run's own periods.
    """

    strategy: SteadyStateStrategy = field(default_factory=SteadyStateStrategy)
    over: Any = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class CyclicStart:
    """Start from the last of repeated cycles of the run's own period under ``strategy``.

    ``over`` is the ``Model`` of the whole simulation when this run is the
    first window of a chain, so each cycle repeats the whole simulation. It is
    ``None`` everywhere else.
    """

    strategy: CyclicSpinupStrategy = field(default_factory=CyclicSpinupStrategy)
    over: Any = field(default=None, repr=False)


@dataclass(frozen=True, slots=True, eq=False)
class PriorState:
    """The last state of an earlier run, read before the solve.

    ``head`` is float64, shaped ``(nlay, ncpl)``, NaN on the cells the store
    marks with its sentinel. ``lake_stages`` maps a lake id to its final stage
    in metres, empty when the earlier run had no lake. ``sfr_stages`` maps an
    SFR reach number, from 0 as FloPy counts it, to its final stage in metres,
    empty unless the earlier run routed SFR with storage. ``path`` is the
    store the state was read from and ``sim_id`` the run it belongs to, when
    known.
    """

    head: np.ndarray
    lake_stages: Mapping[str, float]
    path: str
    sim_id: str | None = None
    sfr_stages: Mapping[int, float] = MappingProxyType({})

    def __post_init__(self) -> None:
        head = np.array(self.head, dtype=np.float64, copy=True)
        if head.ndim != 2:
            raise ValueError(
                f"A prior state head is shaped (nlay, ncpl); got {head.ndim} dimension(s)."
            )
        head.setflags(write=False)
        object.__setattr__(self, "head", head)
        object.__setattr__(self, "lake_stages", _stages(self.lake_stages, str))
        object.__setattr__(self, "sfr_stages", _stages(self.sfr_stages, int))

    def __reduce__(self) -> tuple[object, ...]:
        """Pickle the stages as dicts, which the constructor makes read-only again."""
        return (
            PriorState,
            (
                self.head,
                dict(self.lake_stages),
                self.path,
                self.sim_id,
                dict(self.sfr_stages),
            ),
        )


@dataclass(frozen=True, slots=True, eq=False)
class SolvedState:
    """The head and the lake stages an auxiliary solve of ``solver`` returned, in metres.

    ``lake_stages`` maps a lake id to its stage at the end of the solve, empty
    when the model has no lake. A spin-up cycle that starts from this state
    starts its lakes from these stages.
    """

    head: np.ndarray
    solver: str
    lake_stages: Mapping[str, float] = MappingProxyType({})

    def __post_init__(self) -> None:
        head = np.array(self.head, dtype=np.float64, copy=True)
        head.setflags(write=False)
        object.__setattr__(self, "head", head)
        object.__setattr__(self, "lake_stages", _stages(self.lake_stages, str))

    def __reduce__(self) -> tuple[object, ...]:
        """Pickle the stages as a dict, which the constructor makes read-only again."""
        return (SolvedState, (self.head, self.solver, dict(self.lake_stages)))


def _stages(stages: Mapping[Any, float], key: type) -> Mapping[Any, float]:
    """A read-only copy of ``stages``, each key cast by ``key`` and each stage a float."""
    return MappingProxyType({key(name): float(stage) for name, stage in dict(stages).items()})


InitialState = HeadRule | SteadyStart | CyclicStart | PriorState | SolvedState
"""One of the five states a run starts from."""

INITIAL_STATE_TYPES: tuple[type, ...] = (
    HeadRule,
    SteadyStart,
    CyclicStart,
    PriorState,
    SolvedState,
)
"""The five state classes, in the order this module defines them."""


__all__ = [
    "HEAD_RULE_KINDS",
    "INITIAL_STATE_TYPES",
    "CyclicSpinupStrategy",
    "CyclicStart",
    "HeadRule",
    "InitialState",
    "PriorState",
    "SolvedState",
    "SteadyStart",
    "SteadyStateStrategy",
]
