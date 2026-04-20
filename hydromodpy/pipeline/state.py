"""Pipeline state — the object that flows between pipeline steps.

``PipelineState`` is a frozen dataclass that each step receives as input and
returns a new version of as output. Steps must never mutate a state instance;
instead they produce a successor via :meth:`PipelineState.advance`.

The state is intentionally untyped on its ``data`` payload: the pipeline
orchestration layer stays agnostic of the scientific objects that flow
through it (``Workspace``, ``WorkflowContext``, ``SimulationPlan``, ...).
Steps agree on well-known keys (``"ctx"``, ``"config_path"``, ...).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class PipelineState:
    """State traversing the pipeline, immutable between steps."""

    run_id: str
    step_index: int = -1
    step_name: str = ""
    elapsed_ms: float = 0.0
    data: Mapping[str, Any] = field(default_factory=dict)

    def advance(
        self,
        *,
        step_index: int,
        step_name: str,
        elapsed_ms: float = 0.0,
        data: Mapping[str, Any] | None = None,
        **extra: Any,
    ) -> "PipelineState":
        """Return a successor state for the next step.

        If ``extra`` keyword arguments are provided, they are merged into a
        copy of the current ``data`` mapping (existing keys are overwritten).
        """
        merged: dict[str, Any]
        if data is not None:
            merged = dict(data)
        else:
            merged = dict(self.data)
        if extra:
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

    def with_data(self, **updates: Any) -> "PipelineState":
        """Return a copy of the state with ``data`` merged with ``updates``."""
        merged = dict(self.data)
        merged.update(updates)
        return replace(self, data=merged)


__all__ = ("PipelineState",)
