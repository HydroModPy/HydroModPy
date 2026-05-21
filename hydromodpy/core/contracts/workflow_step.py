"""Canonical Step Protocol shared by every workflow concern.

The runtime-checkable :class:`WorkflowStep` Protocol enforces the minimum
contract every pipeline step must honour: a stable ``name`` and a ``run``
method that maps an input state to an output state. Two extra hooks are
honoured opportunistically:

``depends_on() -> tuple[str, ...]``
    Names of upstream steps whose output state must exist. The Kahn DAG
    sort consumes this method to compute parallel cohorts.

``rebuild_state(prior_state, workspace, run_id)``
    Reconstruct an output state from durable artefacts only. Used at
    resume time so heavy work (solver runs, extraction) is not redone.

``artifacts(state_out) -> tuple[str, ...]``
    Workspace-relative paths persisted by the step. The runner hashes the
    set to produce ``outputs_hash`` rows in the workflow ledger.

Concrete implementations live under :mod:`hydromodpy.workflow.steps` and
re-expose this Protocol via :mod:`hydromodpy.workflow.internals.step`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Protocol, TypeVar, runtime_checkable

TIn = TypeVar("TIn", contravariant=True)
TOut = TypeVar("TOut", covariant=True)


@runtime_checkable
class WorkflowStep(Protocol[TIn, TOut]):
    """Canonical workflow step contract with DAG dependency hooks."""

    name: ClassVar[str]
    tin: ClassVar[type | None]
    tout: ClassVar[type]
    config_sections: ClassVar[tuple[str, ...]]

    def depends_on(self) -> tuple[str, ...]:
        """Return the names of steps whose output state must exist first."""
        ...

    def run(self, state_in: Any) -> Any:
        """Execute the step and return the successor state."""
        ...


@runtime_checkable
class ResumableWorkflowStep(WorkflowStep[TIn, TOut], Protocol[TIn, TOut]):
    """Workflow step that persists durable artefacts and supports resume."""

    def artifacts(self, state_out: Any) -> tuple[str, ...]:
        """Return workspace-relative paths of durable outputs."""
        ...

    def rebuild_state(
        self,
        *,
        prior_state: Any,
        workspace: Path,
        run_id: str,
    ) -> Any:
        """Rebuild the output state by reading durable artefacts only."""
        ...


def step_name(step: object) -> str:
    """Return the canonical name of a workflow step (class attribute)."""
    return str(getattr(step, "name", type(step).__name__))


def step_depends_on(step: object) -> tuple[str, ...]:
    """Read the ``depends_on()`` declaration of a step, defaulting to ()."""
    method = getattr(step, "depends_on", None)
    if method is None:
        return ()
    try:
        result = method()
    except Exception:
        return ()
    if not result:
        return ()
    return tuple(str(item) for item in result)


__all__ = (
    "ResumableWorkflowStep",
    "WorkflowStep",
    "step_depends_on",
    "step_name",
)
