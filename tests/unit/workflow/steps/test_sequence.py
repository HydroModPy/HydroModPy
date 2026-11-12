"""The standard step sequence."""

from __future__ import annotations

from hydromodpy.workflow.steps.sequence import standard_steps

# --- test_rebuild_state_coverage ---
# Every canonical workflow step exposes ``depends_on`` and ``rebuild_state``.


def test_every_step_exposes_rebuild_state() -> None:
    """Every canonical step exposes a rebuild_state hook (in-memory or durable)."""
    for step in standard_steps():
        assert hasattr(step, "rebuild_state"), step.name
