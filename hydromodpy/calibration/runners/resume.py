"""Find a phase that already ran in the session of a case, instead of running it again.

A staged calibration is one session: stage one is a steady solve that closes
in minutes, stage two a daily chronicle over decades. When the transient stage
dies at hour six, ``hmp calibrate --resume`` reopens ``sessions/<case>/``: a
phase whose descriptor says ``completed`` is read back from
``phases/<phase>/session.json`` and ``trials.jsonl``, and the cut phase is
solved again with the cache preloaded from the same journal.

Nothing here decides to reuse anything. It answers what already ran; whether
to trust it is the caller's, and the report says which phases were read from
disk rather than solved.

The one thing this module does verify is whether a completed phase is even
eligible to be trusted: :func:`fingerprint_matches` recomputes, under the
caller's own cache context, the same ``params_hash`` the engine writes per
trial (``hydromodpy.calibration.optim.cache.params_hash``) and checks it
against what the best trial of that phase recorded. A match proves the model,
the mesh and the input files were byte-identical; nothing less.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.results.session.journal import physical_parameters
from hydromodpy.results.session.phase import PhaseDescriptor


def completed_phases(persistence: CalibrationPersistence) -> dict[str, PhaseDescriptor]:
    """Return ``{phase name: descriptor}`` for the phases of the session that finished.

    Only a phase whose descriptor says ``completed`` counts. A ``partial`` one
    produced some trials and stopped, and reusing its best as if the stage had
    converged would report a frozen value the search never settled on.
    """
    return {phase.name: phase for phase in persistence.phases() if phase.status == "completed"}


def best_parameters_of(persistence: CalibrationPersistence, phase: str) -> dict[str, float]:
    """Return the parameters of the best trial one phase recorded, empty when none."""
    best = persistence.held_trial(phase)
    return {} if best is None else physical_parameters(best)


@dataclass(frozen=True, slots=True)
class ReusableStage:
    """One completed phase's best trial, read back with its recorded fingerprint."""

    phase: str
    trial: int
    n_trials: int
    best_cost: float | None
    parameters: dict[str, float]
    params_hash: str | None
    components: dict[str, float] = field(default_factory=dict)


def reusable_stage(persistence: CalibrationPersistence, phase_name: str) -> ReusableStage | None:
    """Return ``phase_name``'s completed result in this session, or ``None``.

    ``None`` when the phase never completed here, or when it left no scored
    trial to read back. Returning something is not a verdict:
    :func:`fingerprint_matches` is what a caller must still ask before trusting it.
    """
    if phase_name not in completed_phases(persistence):
        return None
    best = persistence.held_trial(phase_name)
    if best is None:
        return None
    case = best.only_case
    return ReusableStage(
        phase=phase_name,
        trial=best.trial,
        n_trials=len(persistence.trials(phase_name)),
        best_cost=best.cost,
        parameters=physical_parameters(best),
        params_hash=None if case is None else case.params_hash,
        components={} if case is None else dict(case.components),
    )


def fingerprint_matches(stage: ReusableStage, *, cache_context: Mapping[str, Any]) -> bool:
    """Whether ``stage`` can be trusted under today's ``cache_context``.

    Recomputes the params hash cache key (same function, same rounding) for
    ``stage``'s own recorded values under ``cache_context``, and compares it to
    the hash that was written when the trial ran. A trial with no recorded hash
    (cache disabled at the time) refuses rather than assumes.
    """
    if stage.params_hash is None:
        return False
    from hydromodpy.calibration.optim.cache import params_hash

    return params_hash(stage.parameters, context=cache_context) == stage.params_hash


def trials_another_cost_scored(
    persistence: CalibrationPersistence, phase_name: str, *, cache_context: Mapping[str, Any]
) -> tuple[list[int], list[int]]:
    """Return the completed trials of a phase that today's cost would not reproduce.

    A reopened session adds its trials to the same journal, and the best trial
    of a phase is chosen over every line of it. That choice is fair only when
    one cost scored them all. Each completed trial's recorded ``params_hash``
    is recomputed under ``cache_context``. The first list holds the trials
    whose hash differs, the second those that recorded none and cannot be
    checked.
    """
    from hydromodpy.calibration.optim.cache import params_hash

    differ: list[int] = []
    unchecked: list[int] = []
    for line in persistence.trials(phase_name):
        if line.status != "completed":
            continue
        case = line.only_case
        recorded = None if case is None else case.params_hash
        if recorded is None:
            unchecked.append(line.trial)
        elif params_hash(physical_parameters(line), context=cache_context) != recorded:
            differ.append(line.trial)
    return differ, unchecked


__all__ = [
    "ReusableStage",
    "best_parameters_of",
    "completed_phases",
    "fingerprint_matches",
    "reusable_stage",
    "trials_another_cost_scored",
]
