"""Pipeline step protocol.

A step is a callable with a stable ``name`` that transforms an input
:class:`~hydromodpy.workflow.internals.state.PipelineState` into an output state.

A step declares the payload keys it touches, ``reads`` and ``writes``:

::

    class ResolveStep:
        name = "resolve"
        reads: ClassVar[tuple[str, ...]] = ("cfg", "config_path", "ctx")
        writes: ClassVar[tuple[str, ...]] = ("ctx", "raw_toml")
        config_sections: ClassVar[tuple[str, ...]] = ("workspace", "simulation")

        def run(self, state: PipelineState) -> PipelineState: ...

Both declarations are exact, not indicative:
``tests/unit/architecture/test_step_payload_keys.py`` derives the keys from the
step's own source and fails when a declaration and the code disagree in either
direction. That gate is the whole value of the declaration - the pair it replaced,
``tin`` and ``tout``, named eleven payload classes that nothing ever built and no
production code ever read.

Steps may also declare a ``config_sections`` class variable listing the
dotted TOML subtrees they read from. The attribute is *optional* on the
``Step`` protocol (absent steps are treated as consuming nothing) and is
consumed by :func:`hydromodpy.workflow.internals.dependencies.earliest_affected_step`
to decide which steps must re-run when a calibration overrides a specific
field.

Resume hooks
------------

A persistent step (one that writes durable artefacts) implements two extra
methods checked by the runner via ``hasattr``:

``artifacts(state_out)``
    Return workspace-relative POSIX paths of durable outputs produced by the
    step. The runner hashes these to compute ``outputs_hash`` in the
    ``workflow_steps`` journal. Returning an empty tuple is equivalent to
    not implementing the method: the step is in-memory and gets
    re-executed at resume.

``rebuild_state(prior_state, workspace, run_id)``
    Rebuild the output ``PipelineState`` from disk artefacts only. Called
    by the runner at resume when the step is journal-completed; must not
    execute the heavy operation again (solver run, large extraction).

The runtime-checkable :class:`Step` protocol only enforces ``name`` and
``run``. The :class:`ResumableStep` protocol documents the persistent
contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Protocol, runtime_checkable

from hydromodpy.workflow.internals.state import PipelineState


@runtime_checkable
class Step(Protocol):
    """Canonical pipeline step contract."""

    name: str

    def run(self, state_in: PipelineState) -> PipelineState:
        """Return a successor state produced from ``state_in``."""
        ...


class ResumableStep(Step, Protocol):
    """Optional contract for steps that persist durable artefacts."""

    def artifacts(self, state_out: PipelineState) -> tuple[str, ...]:
        """Return workspace-relative paths of durable outputs."""
        ...

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """Rebuild the output state by reading durable artefacts only."""
        ...


# Lightweight marker mixin used by concrete steps to expose, at runtime, the
# payload keys they touch and the config sections they read.
class _TypedStep:
    """Optional base for steps that want to expose their payload surface."""

    reads: ClassVar[tuple[str, ...]] = ()
    writes: ClassVar[tuple[str, ...]] = ()
    config_sections: ClassVar[tuple[str, ...]] = ()


__all__ = ("ResumableStep", "Step", "_TypedStep")
