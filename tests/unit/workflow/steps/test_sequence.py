"""The standard step sequence: every step can rebuild its state when a run resumes."""

from __future__ import annotations

from hydromodpy.workflow.steps.sequence import standard_steps


def test_every_step_exposes_rebuild_state() -> None:
    for step in standard_steps():
        assert hasattr(step, "rebuild_state"), step.name
