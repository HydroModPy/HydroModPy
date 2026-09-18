"""Pipeline state - the object that flows between pipeline steps.

``PipelineState`` is a frozen dataclass that each step receives as input and
returns a new version of as output. Steps must never mutate a state instance;
instead they produce a successor via :meth:`PipelineState.advance`.

What the payload is
-------------------

``data`` is a mapping of string keys to anything, and its dominant member is
``ctx``, the ``WorkflowContext``: eleven of the twelve steps read it and write it
back, and the twelfth is ``ValidateStep``, which runs before there is one.
Everything the typed-state docstring used to promise -
a resolved data plan, a geographic runtime, a mesh, a setup, an open store, a
solver result - travels on that one object, not as a payload key. Naming the
coupling is the first step of removing it; F8 is that removal.

The payload is a mapping and not something narrower because the runner needs it
to be one, on three paths: a cohort of parallel steps is merged by unioning
``dict(base_state.data)`` with each outcome, a resume writes its workspace in
through :meth:`with_data`, and :meth:`advance` merges keyword arguments.

Eleven frozen payload classes used to be declared here, ``ValidatedState``
through ``ExportedState``, one per step transition, chained by inheritance. They
had zero instantiations anywhere in the repository and lived only as ``tin`` /
``tout`` class variables that no production code read. Ten of their sixteen
fields named no payload key that any step ever wrote, and ``ctx`` - the key every
step but the first reads - appeared in none of them. They documented a
decomposition that did not exist, in the shape of the accumulator F8 dissolves.
What replaced them is a per-step declaration of the payload keys a step reads
and writes, gated in ``tests/unit/architecture/test_step_payload_keys.py``: a
narrow statement that is checked against the code instead of a wide one that was
not.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class PipelineState:
    """State traversing the pipeline, immutable between steps."""

    run_id: str
    step_index: int = -1
    step_name: str = ""
    elapsed_ms: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)

    def advance(
        self,
        *,
        step_index: int,
        step_name: str,
        elapsed_ms: float = 0.0,
        data: dict[str, Any] | None = None,
        **extra: Any,
    ) -> PipelineState:
        """Return a successor state for the next step.

        ``extra`` keyword arguments are merged into a copy of the payload
        (existing keys are overwritten), or into ``data`` when one is passed.
        """
        merged = dict(self.data if data is None else data)
        merged.update(extra)
        return replace(
            self,
            step_index=step_index,
            step_name=step_name,
            elapsed_ms=elapsed_ms,
            data=merged,
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def with_data(self, **updates: Any) -> PipelineState:
        """Return a copy of the state with ``data`` merged with ``updates``."""
        return replace(self, data={**self.data, **updates})


__all__ = ("PipelineState",)
