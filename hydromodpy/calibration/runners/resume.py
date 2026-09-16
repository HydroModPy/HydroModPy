"""Find a stage that already ran, instead of running it again.

A staged calibration holds what each stage froze in a Python list, so the whole
thing lives and dies with one invocation. That is the wrong lifetime for the
shape of the work: stage one is a steady solve that closes in minutes, stage two
a daily chronicle over decades. When the transient stage dies at hour six, the
steady stage that succeeded is gone with it, and the next attempt re-solves a
result that was already correct.

Everything needed to avoid that is on disk. A phase opens its own session row
carrying its name and its place in the chain, and every trial writes its
parameters and its cost. So a completed phase's frozen values are recoverable:
find its session in this chain, take the best trial it recorded, read the
parameters back.

Nothing here decides to reuse anything. It answers what already ran; whether to
trust it is the caller's, and the report says which stages were read from disk
rather than solved.

The one thing this module does verify is whether a completed session is even
eligible to be trusted: :func:`fingerprint_matches` recomputes, under the
caller's own cache context, the same ``params_hash`` the engine already writes
per iteration (``hydromodpy.calibration.optim.cache.params_hash``) and checks it
against what that session's best trial actually recorded. A match proves the
model, the mesh and the input files were byte-identical; nothing less. This is
not a second hash: it is the existing content-addressable cache key, read back
instead of written.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def completed_phases(catalog: Any, root_session_id: str) -> dict[str, str]:
    """Return ``{phase name: session id}`` for the phases of one chain that finished.

    Only a phase whose own session closed as ``completed`` counts. A ``partial``
    one produced some trials and stopped, and reusing its best as if the stage had
    converged would report a frozen value the search never settled on.
    """
    rows = catalog._backend.fetch_all(
        "SELECT cs.phase_name, CAST(cs.session_id AS VARCHAR) "
        "FROM calibration_sessions cs JOIN statuses st ON cs.status_id = st.id "
        "WHERE CAST(cs.root_session_id AS VARCHAR) = ? AND st.code = 'completed' "
        "AND cs.phase_name IS NOT NULL ORDER BY cs.phase_index",
        [str(root_session_id)],
    )
    return {str(name): str(session) for name, session in rows if name}


def _physical_value(name: str, entry: Any) -> float:
    """Return the physical value one parameter entry recorded.

    A trial writes each parameter as ``{"value": ..., "target": ..., "units": ...}``
    (see ``describe_values`` in ``optim/parameters.py``); a bare number is also
    accepted, for a caller that wrote the flat form directly. Anything else is a
    shape this reader does not know, and is refused by name rather than left to
    raise a bare ``TypeError`` deeper in the call.
    """
    if isinstance(entry, Mapping):
        if "value" not in entry:
            raise ValueError(f"parameter {name!r} has no 'value' key: {entry!r}")
        entry = entry["value"]
    if isinstance(entry, bool) or not isinstance(entry, (int, float)):
        raise ValueError(f"parameter {name!r} has an unreadable value: {entry!r}")
    return float(entry)


def _best_trial_row(catalog: Any, session_id: str) -> tuple[dict[str, float], str | None]:
    """Return one session's best trial: its physical values and its params_hash.

    Best means the smallest finite cost among the trials that completed, which is
    the same rule the live search applies. A session with no such trial returns
    nothing rather than the first row it happens to hold. The hash travels with
    the values because it was computed *from* them: read apart, either one alone
    proves nothing about what the trial actually ran under.
    """
    rows = catalog._backend.fetch_all(
        "SELECT parameters, params_hash FROM calibration_iterations "
        "WHERE CAST(session_id AS VARCHAR) = ? AND status = 'completed' "
        "AND objective_value IS NOT NULL ORDER BY objective_value LIMIT 1",
        [str(session_id)],
    )
    if not rows:
        return {}, None
    payload, recorded_hash = rows[0]
    if not payload:
        return {}, None
    values = json.loads(payload) if isinstance(payload, str) else dict(payload)
    parsed = {str(key): _physical_value(str(key), value) for key, value in values.items()}
    return parsed, (str(recorded_hash) if recorded_hash else None)


def best_parameters_of(catalog: Any, session_id: str) -> dict[str, float]:
    """Return the parameters of the best trial one session recorded."""
    values, _ = _best_trial_row(catalog, session_id)
    return values


def frozen_from_disk(
    catalog: Any,
    root_session_id: str,
    *,
    phases: Mapping[str, tuple[str, ...]],
) -> dict[str, dict[str, float]]:
    """Return, per completed phase, the values it froze, read back from disk.

    ``phases`` maps a phase name to the parameter names it was allowed to move,
    so a phase's frozen set is exactly what it calibrated and not everything the
    trial happened to record.
    """
    found: dict[str, dict[str, float]] = {}
    for name, session_id in completed_phases(catalog, root_session_id).items():
        allowed = {str(item) for item in phases.get(name, ())}
        if not allowed:
            continue
        best = best_parameters_of(catalog, session_id)
        kept = {key: value for key, value in best.items() if key in allowed}
        if kept:
            found[name] = kept
    return found


@dataclass(frozen=True, slots=True)
class ReusableStage:
    """One completed phase's best trial, read back with its recorded fingerprint."""

    session_id: str
    n_iterations: int
    best_objective: float | None
    parameters: dict[str, float]
    params_hash: str | None


def reusable_stage(catalog: Any, root_session_id: str, phase_name: str) -> ReusableStage | None:
    """Return ``phase_name``'s completed session in this chain, or ``None``.

    ``None`` when the phase never completed here, or when its best trial left
    no scored candidate to read back. Returning something is not a verdict:
    :func:`fingerprint_matches` is what a caller must still ask before trusting
    it.
    """
    session_id = completed_phases(catalog, root_session_id).get(phase_name)
    if session_id is None:
        return None
    values, recorded_hash = _best_trial_row(catalog, session_id)
    if not values:
        return None
    rows = catalog._backend.fetch_all(
        "SELECT n_iterations, best_objective FROM calibration_sessions "
        "WHERE CAST(session_id AS VARCHAR) = ?",
        [str(session_id)],
    )
    n_iterations, best_objective = rows[0] if rows else (0, None)
    return ReusableStage(
        session_id=session_id,
        n_iterations=int(n_iterations or 0),
        best_objective=None if best_objective is None else float(best_objective),
        parameters=values,
        params_hash=recorded_hash,
    )


def fingerprint_matches(stage: ReusableStage, *, cache_context: Mapping[str, Any]) -> bool:
    """Whether ``stage`` can be trusted under today's ``cache_context``.

    Recomputes the params_hash cache key (same function, same rounding) for
    ``stage``'s own recorded values under ``cache_context``, and compares it to
    the hash that was actually written when the trial ran. A session with no
    recorded hash (cache disabled at the time, or a pre-v2 session) refuses
    rather than assumes: there is nothing to check it against.
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
    "frozen_from_disk",
    "reusable_stage",
]
