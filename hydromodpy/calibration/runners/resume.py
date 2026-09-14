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
"""

from __future__ import annotations

import json
from collections.abc import Mapping
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


def best_parameters_of(catalog: Any, session_id: str) -> dict[str, float]:
    """Return the parameters of the best trial one session recorded.

    Best means the smallest finite cost among the trials that completed, which is
    the same rule the live search applies. A session with no such trial returns
    nothing rather than the first row it happens to hold.
    """
    rows = catalog._backend.fetch_all(
        "SELECT parameters, objective_value FROM calibration_iterations "
        "WHERE CAST(session_id AS VARCHAR) = ? AND status = 'completed' "
        "AND objective_value IS NOT NULL ORDER BY objective_value LIMIT 1",
        [str(session_id)],
    )
    if not rows:
        return {}
    payload = rows[0][0]
    if not payload:
        return {}
    values = json.loads(payload) if isinstance(payload, str) else dict(payload)
    return {str(key): float(value) for key, value in values.items()}


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


__all__ = ["best_parameters_of", "completed_phases", "frozen_from_disk"]
