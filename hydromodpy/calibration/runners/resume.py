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
from dataclasses import dataclass
from typing import Any

from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.results.session.phase import PhaseDescriptor


def completed_phases(persistence: CalibrationPersistence) -> dict[str, PhaseDescriptor]:
    """Return ``{phase name: descriptor}`` for the phases of the session that finished.

    Only a phase whose descriptor says ``completed`` counts. A ``partial`` one
    produced some trials and stopped, and reusing its best as if the stage had
    converged would report a frozen value the search never settled on.
    """
    return {phase.name: phase for phase in persistence.phases() if phase.status == "completed"}


def _physical_value(name: str, entry: Any) -> float:
    """Return the physical value one parameter entry recorded.

    A trial writes each parameter as ``{"value": ..., "target": ..., "units": ...}``
    (see ``describe_values`` in ``optim/parameters.py``); a bare number is also
    accepted. Anything else is a shape this reader does not know, and is refused
    by name rather than left to raise a bare ``TypeError`` deeper in the call.
    """
    if isinstance(entry, Mapping):
        if "value" not in entry:
            raise ValueError(f"parameter {name!r} has no 'value' key: {entry!r}")
        entry = entry["value"]
    if isinstance(entry, bool) or not isinstance(entry, (int, float)):
        raise ValueError(f"parameter {name!r} has an unreadable value: {entry!r}")
    return float(entry)


def physical_values(params: Mapping[str, Any]) -> dict[str, float]:
    """Return the physical value of every parameter a trial line recorded."""
    return {str(name): _physical_value(str(name), value) for name, value in params.items()}


def best_parameters_of(persistence: CalibrationPersistence, phase: str) -> dict[str, float]:
    """Return the parameters of the best trial one phase recorded, empty when none."""
    best = persistence.best_trial(phase)
    return {} if best is None else physical_values(best.params)


@dataclass(frozen=True, slots=True)
class ReusableStage:
    """One completed phase's best trial, read back with its recorded fingerprint."""

    phase: str
    trial: int
    n_iterations: int
    best_objective: float | None
    parameters: dict[str, float]
    params_hash: str | None


def reusable_stage(persistence: CalibrationPersistence, phase_name: str) -> ReusableStage | None:
    """Return ``phase_name``'s completed result in this session, or ``None``.

    ``None`` when the phase never completed here, or when it left no scored
    trial to read back. Returning something is not a verdict:
    :func:`fingerprint_matches` is what a caller must still ask before trusting it.
    """
    if phase_name not in completed_phases(persistence):
        return None
    best = persistence.best_trial(phase_name)
    if best is None:
        return None
    return ReusableStage(
        phase=phase_name,
        trial=best.trial,
        n_iterations=len(persistence.trials(phase_name)),
        best_objective=best.objective,
        parameters=physical_values(best.params),
        params_hash=best.params_hash,
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


__all__ = [
    "ReusableStage",
    "best_parameters_of",
    "completed_phases",
    "fingerprint_matches",
    "physical_values",
    "reusable_stage",
]
