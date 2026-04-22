"""Pipeline step protocol.

A step is a callable with a stable ``name`` that transforms an input
:class:`~hydromodpy.pipeline.state.PipelineState` into an output state.

The protocol is generic over the input/output payload types ``TIn`` and
``TOut`` so that statically-checked steps can declare:

::

    class ResolveStep:
        name = "resolve"
        tin: ClassVar[type] = ValidatedState
        tout: ClassVar[type] = ResolvedState

        def run(
            self, state: PipelineState[ValidatedState]
        ) -> PipelineState[ResolvedState]: ...

The protocol stays runtime-checkable on the structural shape (``name`` +
``run``); the type variables are erased at runtime.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar, runtime_checkable

from hydromodpy.pipeline.state import PipelineState

TIn = TypeVar("TIn", contravariant=True)
TOut = TypeVar("TOut", covariant=True)


@runtime_checkable
class Step(Protocol[TIn, TOut]):
    """Canonical pipeline step contract."""

    name: str

    def run(self, state_in: PipelineState[TIn]) -> PipelineState[TOut]:
        """Return a successor state produced from ``state_in``."""
        ...


# Lightweight marker mixin used by concrete steps to expose their TIn/TOut
# at runtime (the Protocol type variables are erased). Steps may also assign
# class-level attributes ``tin`` and ``tout`` directly.
class _TypedStep:
    """Optional base for steps that want to expose their ``tin``/``tout``."""

    tin: type[Any] | None = None
    tout: type[Any] | None = None


__all__ = ("Step", "TIn", "TOut", "_TypedStep")
