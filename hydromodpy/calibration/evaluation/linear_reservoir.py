"""The forward model this build ships: one control volume, emptying in closed form.

What it is for
--------------
A calibration scored through the document's criteria has three parts that can
each be wrong on their own: the model, the outputs it is asked for, and the
blocks that weigh them. Naming this model in ``[calibration] forward_model``
takes the first one out of the question. It runs no solver, its recession is a
closed form, and its answer for a given sample can be written down in advance,
so a document that scores it wrongly is a document whose criteria are wrong.

It is also what the forward-model route is exercised on in this repository:
:mod:`tests/contract/test_trial_evaluator_contract` runs a whole ask/tell search
over it, and the proof that a change of metric or of weight moves the cost is
run against it as well -- with the model untouched between the two runs, which
is the point of the port.

What it computes
----------------
One reservoir of area :data:`RESERVOIR_AREA_M2`, holding
:data:`INITIAL_STORAGE_M3` at the start of a recession sampled daily over
:data:`RECESSION_DAYS` steps::

    S(t) = S0 * exp(-k * t)        storage, m3
    Q(t) = k * S(t)                outlet flow, m3/day
    h(t) = S(t) / (A * porosity)   head over the reservoir floor, m

``k`` is the recession coefficient in 1/day and ``porosity`` the drainable
porosity. A sample naming neither is run on the reference pair, which is what
makes a document declaring no parameter a legal rehearsal rather than a crash.

What it refuses to invent
-------------------------
It is lumped: it has one outlet and one cell, and it carries no calendar. So it
refuses an output placed on a lake, on a cell that is not its own, and two
outputs of one variable placed at two different boundaries -- answering those
would mean serving the same values twice under two names and letting a document
believe it had scored two places. It returns no timestamps for the same reason:
its time axis is days since the start of a recession, and dating it against a
record would be an invention. Outputs scored against it are therefore scored
positionally, on ``observed_values``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import ClassVar

import numpy as np

from hydromodpy.calibration.evaluation.forward import ForwardOutcome, ForwardRequest
from hydromodpy.core.contracts.observables import (
    ObservableRequest,
    ObservableResult,
    select_time_indices,
)

K_REFERENCE_PER_DAY = 1e-4
"""Recession coefficient used for a sample that does not name ``k``."""

POROSITY_REFERENCE = 0.155
"""Drainable porosity used for a sample that does not name ``porosity``."""

INITIAL_STORAGE_M3 = 1_000_000.0
RESERVOIR_AREA_M2 = 10_000_000.0
RECESSION_DAYS = 30
"""Number of daily steps the recession is sampled over."""

PARAMETERS: tuple[str, ...] = ("k", "porosity")
"""The only two names a sample may carry."""

VARIABLES: Mapping[str, str] = {"discharge": "m3/d", "head": "m"}
"""What it serves, and the unit each is served in."""

SUPPORTED: tuple[str, ...] = ("boundary", "cell")
"""Where an output may be placed: its outlet, or its single cell."""

ONLY_CELL = (0, 0, 0)
"""The one cell a lumped reservoir has."""


class LinearReservoirForwardModel:
    """Serve the outlet flow and the head of one reservoir for a sample.

    Built by :func:`hydromodpy.calibration.evaluation.forward_registry.create`,
    which binds nothing: the model has no configuration of its own, and every
    number it needs is either a sample value or a constant of this module.
    """

    model_id: ClassVar[str] = "linear_reservoir"

    def simulate(self, request: ForwardRequest) -> ForwardOutcome:
        """Return one result per observable request, or raise saying why not."""
        k, porosity = _sample(request.values)
        _refuse_two_places_for_one_variable(request.observables)
        observables: dict[str, ObservableResult] = {}
        for observable in request.observables:
            _refuse_a_placement_it_does_not_have(observable)
            values = _recession(observable.name, k=k, porosity=porosity)
            kept = select_time_indices(RECESSION_DAYS, observable.times)
            observables[observable.id] = ObservableResult(
                request_id=observable.id,
                values=values[kept],
                units=VARIABLES[observable.name],
            )
        return ForwardOutcome(
            observables=observables,
            diagnostics={"linear_reservoir.recession_days": float(RECESSION_DAYS)},
        )


def _sample(values: Mapping[str, float]) -> tuple[float, float]:
    """Read ``k`` and ``porosity`` out of a sample, or say what is wrong with it."""
    unknown = sorted(set(values) - set(PARAMETERS))
    if unknown:
        raise ValueError(
            f"{LinearReservoirForwardModel.model_id!r} is a lumped reservoir and knows "
            f"{', '.join(PARAMETERS)}; the sample also carries {', '.join(unknown)}. A "
            "parameter it cannot place is not one it should quietly ignore."
        )
    k = _finite(values.get("k", K_REFERENCE_PER_DAY), "k")
    porosity = _finite(values.get("porosity", POROSITY_REFERENCE), "porosity")
    if k <= 0.0:
        raise ValueError(f"k={k!r} is a recession coefficient in 1/day and has to be positive.")
    if not 0.0 < porosity <= 1.0:
        raise ValueError(f"porosity={porosity!r} has to lie in (0, 1].")
    return k, porosity


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
            f"output {observable.id!r} asks for {observable.name!r}, and "
            f"{LinearReservoirForwardModel.model_id!r} serves {', '.join(sorted(VARIABLES))}."
        )
    if observable.support not in SUPPORTED:
        raise ValueError(
            f"output {observable.id!r} is placed on support {observable.support!r}, and a "
            f"lumped reservoir has only {', '.join(SUPPORTED)}: one outlet and one cell."
        )
    if observable.support == "cell" and tuple(observable.cell or ()) != ONLY_CELL:
        raise ValueError(
            f"output {observable.id!r} reads cell {observable.cell!r}, and this model is one "
            f"control volume: its only cell is {ONLY_CELL}."
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
            f"{', '.join(ambiguous)} {'is' if len(ambiguous) == 1 else 'are'} declared under two "
            "placements, and a lumped reservoir is one control volume with one outlet: it "
            "cannot tell them apart. Its outlet and its only cell count as two here, because "
            "both outputs would receive the same values under two names and the document would "
            "read that as two places scored."
        )


def _recession(variable: str, *, k: float, porosity: float) -> np.ndarray:
    """Return the daily series of *variable* over the recession."""
    days = np.arange(RECESSION_DAYS, dtype=float)
    storage = INITIAL_STORAGE_M3 * np.exp(-k * days)
    values = storage * k if variable == "discharge" else storage / (RESERVOIR_AREA_M2 * porosity)
    if not np.all(np.isfinite(values)):
        raise ValueError(
            f"the recession of {variable!r} is not finite for k={k!r} and porosity={porosity!r}."
        )
    return values


__all__ = [
    "INITIAL_STORAGE_M3",
    "K_REFERENCE_PER_DAY",
    "POROSITY_REFERENCE",
    "RECESSION_DAYS",
    "RESERVOIR_AREA_M2",
    "LinearReservoirForwardModel",
]
