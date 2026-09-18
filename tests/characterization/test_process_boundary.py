"""What crosses a process boundary, and what the redesign made cross.

``WorkflowContext`` is threaded through every pipeline step. The repository
guards it with an AST scan that proves no module imports ``pickle``; nothing
ever attempted the round trip and observed what happens. This test attempts
it on a context that has just run a real simulation.

Until F8b it failed on the one field that could not survive: ``ctx.store``, a
live DuckDB connection holding an ``RLock``. The catalog of a run is now
opened by whoever writes to it, for the span of that write, so the context
carries no handle and the round trip completes.
"""

from __future__ import annotations

import pickle


def test_the_runtime_state_survives_a_process_boundary(live_project) -> None:
    """A real context, after a real run, pickles and comes back."""
    context = live_project.workflow_context
    restored = pickle.loads(pickle.dumps(context))
    assert restored.sim_id == context.sim_id
    assert restored.config_path == context.config_path
