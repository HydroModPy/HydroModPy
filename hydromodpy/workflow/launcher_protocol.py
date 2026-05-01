"""Launcher Protocol for simulation orchestration backends.

A ``Launcher`` drives the execution of a resolved :class:`SimulationPlan`
against a runtime state. The default in-tree implementation is
:class:`hydromodpy.simulation.execution.runner.SimulationRunner`, which
walks runs sequentially in the current process.

Conforming alternative backends (HPC SLURM, cloud batch, in-memory debug,
distributed) can be plugged behind this same contract without changing
the orchestrator. Implementations conform structurally - no base class.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from hydromodpy.simulation.planning.plan import SimulationPlan


@runtime_checkable
class Launcher(Protocol):
    """Drive a resolved ``SimulationPlan`` against a runtime state.

    The launcher is responsible for walking ``plan.runs`` in order, for
    setting up each process-family block, and for storing the produced
    models back into ``state.execution.models_by_run_id``.

    The single ``execute`` method takes the plan and the workflow state.
    Side-effects are observed through ``state`` mutations and through any
    optional callbacks the implementation supports (e.g. ``after_run``).
    """

    def execute(
        self,
        plan: SimulationPlan,
        state: Any,
        *,
        callbacks: Any | None = None,
    ) -> None:
        """Execute every planned run in order against ``state``.

        ``state`` is typed as ``Any`` because the workflow context is
        defined in the ``core`` layer and this Protocol lives in
        ``workflow``: keeping the parameter loose preserves the layered
        DAG while letting concrete launchers depend on the real type.
        ``callbacks`` is launcher-specific metadata; the default launcher
        accepts :class:`hydromodpy.simulation.execution.runner.ProcessCallbacks`.
        """
