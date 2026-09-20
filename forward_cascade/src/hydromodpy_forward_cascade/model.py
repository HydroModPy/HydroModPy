"""A two-reservoir cascade published as a HydroModPy forward model.

What it is, and what it is for
------------------------------
HydroModPy names a forward model in ``[calibration] forward_model`` and resolves
it through the ``hydromodpy.calibration.forward_model`` entry-point group. This
distribution registers ``two_reservoir_cascade`` there and nothing in
HydroModPy names it back: the only thing the host knows is the port -- a
parameter sample in, named observables out.

The point of the port is where the score is decided. Its sibling distribution
``hydromodpy-evaluator-reservoir`` implements the *evaluator* port, so it
returns a cost and therefore also chooses which quantity is compared and how the
comparison is weighed; changing either means editing that wheel. This model
returns observables and never a cost. Which output is scored, under which metric
and with which weight, is written in the calibration document, and this file
does not read it.

The physics, in closed form
---------------------------
Two linear stores in series, sampled daily over :data:`RECESSION_DAYS` steps.
The upper store empties at ``k_fast``; a fraction :data:`SPLIT_TO_SLOW` of its
outflow feeds the lower store, which empties at ``k_slow``, and the rest reaches
the outlet directly::

    S1(t) = S0 exp(-k1 t)
    S2(t) = f S0 k1 / (k2 - k1) * (exp(-k1 t) - exp(-k2 t))
    Q(t)  = (1 - f) k1 S1(t) + k2 S2(t)
    h(t)  = S2(t) / (A n)

``S`` are storages in m3, ``Q`` the outlet flow in m3/day, ``h`` the head over
the lower store's floor in m, ``k`` the two recession coefficients in 1/day,
``A`` the area in m2 and ``n`` the drainable porosity, a constant here.

The direct fraction is what makes the *discharge* tell the two coefficients
apart. Measured with ``f = 1``, exchanging ``k_fast`` and ``k_slow`` moves ``Q``
by ``7e-12`` on a scale of ``3.3e4`` -- the convolution of two exponentials does
not care which one came first -- and by ``2e4`` with ``f = 0.9``. A document
scoring the outlet alone would otherwise have two equally good optima
describing different catchments. The head is not symmetric either way: it is
the storage of the lower store, which carries the ``k1 / (k2 - k1)`` factor
undivided, so a document scoring it tells the pair apart without the split.

What it refuses
---------------
It is lumped: one outlet, one cell, no calendar. It refuses a variable it does
not serve, a placement it does not have, and one variable asked for at two
places, because answering those would hand the document the same numbers twice
under two names and let it believe it had scored two places. It returns no
timestamps, so an output scored against it is scored positionally, on
``observed_values``.

Refusal is a raised exception on purpose: the port states that the evaluator
composing this model with the document's criteria turns a refusal into a failed
trial carrying ``nan``, so a model does not reproduce the outcome discipline of
the ask/tell loop.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, ClassVar

import numpy as np

from hydromodpy.calibration.evaluation.forward import ForwardOutcome, ForwardRequest
from hydromodpy.core.contracts.observables import (
    ObservableRequest,
    ObservableResult,
    select_time_indices,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy.typing import NDArray

MODEL_ID = "two_reservoir_cascade"

K_FAST_REFERENCE_PER_DAY = 0.25
"""Upper-store coefficient used for a sample that does not name ``k_fast``."""

K_SLOW_REFERENCE_PER_DAY = 0.05
"""Lower-store coefficient used for a sample that does not name ``k_slow``."""

INITIAL_STORAGE_M3 = 1_000_000.0
RESERVOIR_AREA_M2 = 10_000_000.0
POROSITY = 0.155
"""Drainable porosity. A constant, not a parameter: the two coefficients are."""

SPLIT_TO_SLOW = 0.9
"""Fraction of the upper outflow routed through the lower store."""

RECESSION_DAYS = 30
"""Number of daily steps the answer is sampled over."""

PARAMETERS: tuple[str, ...] = ("k_fast", "k_slow")
"""The only two names a sample may carry."""

VARIABLES: Mapping[str, str] = {"discharge": "m3/d", "head": "m"}
"""What it serves, and the unit each is served in."""

SUPPORTED: tuple[str, ...] = ("boundary", "cell")
"""Where an output may be placed: its outlet, or its single cell."""

ONLY_CELL = (0, 0, 0)
"""The one cell a lumped cascade has."""

COINCIDENT_RATIO = 1e-6
"""Relative gap below which the limit form replaces the general one.

Relative and not absolute: the cancellation in ``exp(-k1 t) - exp(-k2 t)`` is
governed by ``gap / k``, not by ``gap``. Measured at ``k_fast = 0.25``, the
general form is already down to four correct digits at an absolute gap of
``1e-12``, where the limit form is exact to ``2e-16``. At this relative
threshold the two forms differ by ``3.7e-6``, which is the genuine ``O(gap t)``
term and not a loss of precision: the crossover is where the two answers still
agree, rather than where one of them has already stopped being one.
"""


class CascadeForwardModel:
    """Serve the outlet flow and the head of a two-store cascade for a sample.

    Built by HydroModPy's forward-model registry, which binds only the
    constructor options a class names. This one names none: every number it
    needs is either a sample value or a constant of this module, so it is
    buildable by any caller that can resolve its id.
    """

    model_id: ClassVar[str] = MODEL_ID

    def simulate(self, request: ForwardRequest) -> ForwardOutcome:
        """Return one result per observable request, or raise saying why not."""
        k_fast, k_slow = _sample(request.values)
        _refuse_two_places_for_one_variable(request.observables)
        storage = _lower_storage(k_fast, k_slow)
        observables: dict[str, ObservableResult] = {}
        for observable in request.observables:
            _refuse_a_placement_it_does_not_have(observable)
            values = _series(observable.name, storage, k_fast=k_fast, k_slow=k_slow)
            kept = select_time_indices(RECESSION_DAYS, observable.times)
            observables[observable.id] = ObservableResult(
                request_id=observable.id,
                values=values[kept],
                units=VARIABLES[observable.name],
            )
        return ForwardOutcome(
            observables=observables,
            diagnostics={
                "cascade.recession_days": float(RECESSION_DAYS),
                "cascade.split_to_slow": SPLIT_TO_SLOW,
            },
        )


def _sample(values: Mapping[str, float]) -> tuple[float, float]:
    """Read the two coefficients out of a sample, or say what is wrong with it."""
    unknown = sorted(set(values) - set(PARAMETERS))
    if unknown:
        raise ValueError(
            f"{MODEL_ID!r} is a two-store cascade and knows {', '.join(PARAMETERS)}; the "
            f"sample also carries {', '.join(unknown)}. A parameter it cannot place is not "
            "one it should quietly ignore."
        )
    k_fast = _finite(values.get("k_fast", K_FAST_REFERENCE_PER_DAY), "k_fast")
    k_slow = _finite(values.get("k_slow", K_SLOW_REFERENCE_PER_DAY), "k_slow")
    for name, value in (("k_fast", k_fast), ("k_slow", k_slow)):
        if value <= 0.0:
            raise ValueError(f"{name}={value!r} is a recession coefficient in 1/day.")
    return k_fast, k_slow


def _finite(value: object, name: str) -> float:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name}={value!r} is not a number this model can read.") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{name}={value!r} is not a finite number.")
    return numeric


def _refuse_a_placement_it_does_not_have(observable: ObservableRequest) -> None:
    """Refuse a variable it does not serve, or a place it does not have."""
    if observable.name not in VARIABLES:
        raise ValueError(
            f"output {observable.id!r} asks for {observable.name!r}, and {MODEL_ID!r} serves "
            f"{', '.join(sorted(VARIABLES))}."
        )
    if observable.support not in SUPPORTED:
        raise ValueError(
            f"output {observable.id!r} is placed on support {observable.support!r}, and a "
            f"lumped cascade has only {', '.join(SUPPORTED)}: one outlet and one cell."
        )
    if observable.support == "cell" and tuple(observable.cell or ()) != ONLY_CELL:
        raise ValueError(
            f"output {observable.id!r} reads cell {observable.cell!r}, and this model is two "
            f"control volumes at one place: its only cell is {ONLY_CELL}."
        )


def _refuse_two_places_for_one_variable(observables: Sequence[ObservableRequest]) -> None:
    """Refuse one variable asked for at two places, which it cannot tell apart."""
    placements: dict[str, set[tuple[object, object]]] = {}
    for observable in observables:
        placements.setdefault(observable.name, set()).add(
            (observable.key, tuple(observable.cell) if observable.cell else None)
        )
    ambiguous = sorted(name for name, places in placements.items() if len(places) > 1)
    if ambiguous:
        raise ValueError(
            f"{', '.join(ambiguous)} {'is' if len(ambiguous) == 1 else 'are'} declared under "
            "two placements, and this model has one outlet and one cell: both outputs would "
            "receive the same values under two names and the document would read that as two "
            "places scored."
        )


def _lower_storage(k_fast: float, k_slow: float) -> NDArray[np.float64]:
    """Return the daily storage of the lower store, in m3.

    The coincident case is not an edge to be guarded against but the limit of
    the same solution: as ``k_slow`` approaches ``k_fast`` the ratio tends to
    ``k t``, and evaluating the general form there subtracts two exponentials
    that agree to their last digits before dividing by the gap between them. The
    declared grid never comes close, but nothing stops a gradient or a
    population search from proposing the pair: the two intervals overlap on
    ``[0.025, 0.5]``.
    """
    days = np.arange(RECESSION_DAYS, dtype=float)
    gap = k_slow - k_fast
    if abs(gap) < COINCIDENT_RATIO * max(k_fast, k_slow):
        ratio = k_fast * days * np.exp(-k_fast * days)
    else:
        ratio = (k_fast / gap) * (np.exp(-k_fast * days) - np.exp(-k_slow * days))
    storage = SPLIT_TO_SLOW * INITIAL_STORAGE_M3 * ratio
    if not np.all(np.isfinite(storage)):
        raise ValueError(
            f"the cascade storage is not finite for k_fast={k_fast!r} and k_slow={k_slow!r}."
        )
    return storage


def _series(
    variable: str, storage: NDArray[np.float64], *, k_fast: float, k_slow: float
) -> NDArray[np.float64]:
    """Return the daily series of *variable* over the recession."""
    if variable == "head":
        values = storage / (RESERVOIR_AREA_M2 * POROSITY)
    else:
        days = np.arange(RECESSION_DAYS, dtype=float)
        upper = INITIAL_STORAGE_M3 * np.exp(-k_fast * days)
        values = (1.0 - SPLIT_TO_SLOW) * k_fast * upper + k_slow * storage
    if not np.all(np.isfinite(values)):
        raise ValueError(
            f"the series of {variable!r} is not finite for k_fast={k_fast!r} and k_slow={k_slow!r}."
        )
    return values


__all__ = [
    "INITIAL_STORAGE_M3",
    "K_FAST_REFERENCE_PER_DAY",
    "K_SLOW_REFERENCE_PER_DAY",
    "MODEL_ID",
    "POROSITY",
    "RECESSION_DAYS",
    "RESERVOIR_AREA_M2",
    "SPLIT_TO_SLOW",
    "CascadeForwardModel",
]
