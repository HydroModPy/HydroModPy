"""Progress relay draining for the isolated MF6 API child process.

``_drain_progress`` has no MODFLOW or subprocess dependency: it only reads
``(completed, total)`` tuples off a plain ``queue.Queue`` and forwards them to
a progress-bar handle. It used to live in the ``modflowapi``-gated
integration module, where it was skipped whenever that optional dependency
was missing.
"""

from __future__ import annotations

import queue

import pytest

from hydromodpy.solver.modflow6.api.api_subprocess import _drain_progress


@pytest.mark.fast
def test_drain_progress_applies_total_then_completed() -> None:
    relay: queue.Queue = queue.Queue()
    relay.put((0, 5))
    relay.put((3, None))

    updates: list[tuple[str, float]] = []

    class _Bar:
        def update(self, *, completed=None, total=None) -> None:
            if total is not None:
                updates.append(("total", total))
            if completed is not None:
                updates.append(("completed", completed))

    _drain_progress(relay, _Bar())
    assert ("total", 5.0) in updates
    assert updates[-1] == ("completed", 3.0)
