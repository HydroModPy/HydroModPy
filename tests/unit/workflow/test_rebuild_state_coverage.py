"""Every canonical workflow step exposes ``depends_on`` and ``rebuild_state``."""

from __future__ import annotations

from hydromodpy.workflow.orchestrator import standard_steps


def test_every_step_declares_depends_on() -> None:
    """The 12 canonical steps all return a tuple from ``depends_on``."""
    for step in standard_steps():
        assert hasattr(step, "depends_on"), step.name
        deps = step.depends_on()
        assert isinstance(deps, tuple), step.name
        assert all(isinstance(d, str) for d in deps), step.name


def test_every_step_exposes_rebuild_state() -> None:
    """Every canonical step exposes a rebuild_state hook (in-memory or durable)."""
    for step in standard_steps():
        assert hasattr(step, "rebuild_state"), step.name


def test_depends_on_references_existing_step_names() -> None:
    """Each declared dependency names another step in the canonical pipeline."""
    steps = standard_steps()
    declared = {step.name for step in steps}
    for step in steps:
        for dep in step.depends_on():
            assert dep in declared, (step.name, dep)
