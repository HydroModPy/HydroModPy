"""Pipeline step protocol.

A step is a callable with a stable ``name`` that transforms an input
:class:`~hydromodpy.pipeline.state.PipelineState` into an output state.

Steps are deliberately declared via a ``Protocol`` so that any object — a
plain class with a ``__call__``, a lambda wrapped in a dataclass, a closure —
can act as a step provided it exposes ``name`` and ``run``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from hydromodpy.pipeline.state import PipelineState


@runtime_checkable
class Step(Protocol):
    """Canonical pipeline step contract."""

    name: str

    def run(self, state_in: PipelineState) -> PipelineState:
        """Return a successor state produced from ``state_in``."""
        ...


__all__ = ("Step",)
