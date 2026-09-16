"""What crosses a process boundary today, and what the redesign must make cross.

``WorkflowContext`` is threaded through every pipeline step. The repository
guards it with an AST scan that proves no module imports ``pickle``; nothing
ever attempted the round trip and observed what happens. This test attempts it
on a context that has just run a real simulation, so the failure is the real
one: a live DuckDB connection with its ``RLock`` sits on ``ctx.store``, and the
solver models sit on ``ctx.execution``.

Phase F8 dissolves ``WorkflowContext``; the day a capability's state is a
serialisable request, this strict xfail turns into a failure and says so.
"""

from __future__ import annotations

import pickle

import pytest


@pytest.mark.xfail(
    strict=True,
    reason="A2: ctx.store is a live DuckDB connection holding an RLock",
)
def test_the_runtime_state_survives_a_process_boundary(live_project) -> None:
    """A real context, after a real run, pickles and comes back."""
    context = live_project.workflow_context
    restored = pickle.loads(pickle.dumps(context))
    assert restored.sim_id == context.sim_id
    assert restored.config_path == context.config_path
