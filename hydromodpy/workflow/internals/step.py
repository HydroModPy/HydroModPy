"""Pipeline step protocol.

A step is a callable with a stable ``name`` that transforms an input
:class:`~hydromodpy.workflow.internals.state.PipelineState` into an output state.

The protocol is generic over the input/output payload types ``TIn`` and
``TOut`` so that statically-checked steps can declare:

::

    class ResolveStep:
        name = "resolve"
        tin: ClassVar[type] = ValidatedState
        tout: ClassVar[type] = ResolvedState
        config_sections: ClassVar[tuple[str, ...]] = ("workspace", "simulation")

        def run(
            self, state: PipelineState[ValidatedState]
        ) -> PipelineState[ResolvedState]: ...

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
from typing import Any, ClassVar, Protocol, TypeVar, runtime_checkable

from hydromodpy.workflow.internals.state import PipelineState

TIn = TypeVar("TIn", contravariant=True)
TOut = TypeVar("TOut", covariant=True)


@runtime_checkable
class Step(Protocol[TIn, TOut]):
    """Canonical pipeline step contract."""

    name: str

    def run(self, state_in: PipelineState[TIn]) -> PipelineState[TOut]:
        """Return a successor state produced from ``state_in``."""
        ...


class ResumableStep(Step[TIn, TOut], Protocol[TIn, TOut]):
    """Optional contract for steps that persist durable artefacts."""

    def artifacts(self, state_out: PipelineState[TOut]) -> tuple[str, ...]:
        """Return workspace-relative paths of durable outputs."""
        ...

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState[TIn],
        workspace: Path,
        run_id: str,
    ) -> PipelineState[TOut]:
        """Rebuild the output state by reading durable artefacts only."""
        ...


# Lightweight marker mixin used by concrete steps to expose their TIn/TOut
# at runtime (the Protocol type variables are erased). Steps may also assign
# class-level attributes ``tin`` and ``tout`` directly.
class _TypedStep:
    """Optional base for steps that want to expose their ``tin``/``tout``."""

    tin: type[Any] | None = None
    tout: type[Any] | None = None
    config_sections: ClassVar[tuple[str, ...]] = ()


__all__ = ("ResumableStep", "Step", "TIn", "TOut", "_TypedStep")
