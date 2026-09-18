"""Immutable runtime objects describing a resolved simulation plan.

This module is the small contract shared by the planner and the runner.
The user-facing TOML remains declarative and compact, while these dataclasses
store the expanded execution schedule the runtime can consume directly.

The main design choice is to keep these objects frozen and explicit:

- one ``ProcessRun`` represents exactly one process/solver pair,
- dependencies are stored as concrete upstream run ids,
- the ``SimulationPlan`` preserves the execution order chosen by the planner.

That makes the schedule easy to inspect in tests, logs, and debugging sessions
without re-reading or re-interpreting the original configuration file.

``RunContext`` and ``RunExecutionResult`` live here so that both the runner
and the adapters share a single import source without circular dependencies.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hydromodpy.core.state.run_state import RunState


@dataclass(frozen=True)
class ProcessRun:
    """One concrete execution unit produced by the planner.

    A single declarative ``[[simulation.process]]`` entry can expand to several
    ``ProcessRun`` objects when multiple solvers are listed. ``depends_on``
    stores resolved run identifiers, so the runner can retrieve the exact
    upstream model instance that must already exist.
    """

    id: str
    process_id: str
    process_type: str
    solver: str
    backend: str | None = None
    # Dependencies refer to concrete run ids (for example "flow_1::modflow_nwt").
    depends_on: tuple[str, ...] = field(default_factory=tuple)

    @staticmethod
    def build_id(process_id: str, solver: str) -> str:
        """Canonical run-id format: ``"<process_id>::<solver>"``."""
        return f"{process_id}::{solver}"

    @property
    def is_solver_backed(self) -> bool:
        """Return True when this run is delegated to a registered solver adapter."""
        return self.process_type != "mesh"


@dataclass(frozen=True)
class SimulationPlan:
    """Resolved execution schedule ready for runtime orchestration.

    ``runs`` is intentionally ordered: the runner executes it sequentially
    without re-sorting or topological reconstruction.
    """

    name: str
    description: str
    # Preserve the exact execution order emitted by the planner.
    runs: tuple[ProcessRun, ...] = field(default_factory=tuple)

    def is_empty(self) -> bool:
        """Return ``True`` when the planner emitted no executable run."""
        return not self.runs

    def _repr_html_(self) -> str:
        header = (
            "<div><b>SimulationPlan</b> "
            f"<code>{self.name}</code>"
            f"<div style='font-size:0.85em;color:#666'>{self.description}</div>"
        )
        if not self.runs:
            return header + "<i>(empty plan)</i></div>"
        rows = "".join(
            "<tr>"
            f"<td><code>{r.id}</code></td>"
            f"<td>{r.process_type}</td>"
            f"<td>{r.solver}</td>"
            f"<td>{', '.join(r.depends_on) if r.depends_on else '&mdash;'}</td>"
            "</tr>"
            for r in self.runs
        )
        table = (
            "<table style='font-size:0.85em;border-collapse:collapse'>"
            "<thead><tr>"
            "<th style='text-align:left'>run id</th>"
            "<th style='text-align:left'>type</th>"
            "<th style='text-align:left'>solver</th>"
            "<th style='text-align:left'>depends on</th>"
            "</tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
        return header + table + "</div>"


# ---------------------------------------------------------------------------
# Runtime contracts - shared by runner and adapters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunContext:
    """Resolved runtime context passed to one solver adapter.

    By the time an adapter receives this object, the planner has already fixed
    the run order and the runner has already resolved the concrete upstream
    models referenced by ``run.depends_on``.

    ``state`` is the reduced view of the workflow runtime an adapter may read
    (:class:`hydromodpy.core.state.run_state.RunState`), never the workflow
    context itself.

    ``store`` is the catalog handle of the enclosing run, or ``None`` when the
    run writes no index (a calibration trial). It is a borrowed handle whose
    owner closes it: an adapter reads or writes through it during its own
    ``execute`` and keeps no reference past the call.

    ``model``, ``output_dir`` and ``lumped_cache`` are what *this* run produced:
    the solver model the adapter built, the directory the solver wrote into,
    and the series a lightweight lumped run kept in RAM instead of writing.
    All three are ``None`` while the run executes, because it has produced
    nothing yet, and they are set on the contexts built after it completed.
    They are carried here rather than looked up in a registry: every consumer
    asked the registry for the entry keyed by its own ``run.id``, which is not
    a registry lookup but a self-reference routed through shared mutable state.
    """

    plan: SimulationPlan
    run: ProcessRun
    state: RunState
    dependency_models: tuple[Any, ...] = ()
    store: Any = None
    model: Any = None
    output_dir: Path | None = None
    lumped_cache: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, RunState):
            raise TypeError(
                "RunContext.state must be a RunState view of the workflow runtime, "
                f"got {type(self.state).__name__}."
            )

    @classmethod
    def of(
        cls,
        ctx: Any,
        *,
        plan: SimulationPlan,
        run: ProcessRun,
        store: Any = None,
    ) -> RunContext:
        """Return the context of ``run`` inside the pipeline runtime ``ctx``.

        The single construction path for every consumer that runs *after* the
        solver: it reads the produced model and the solver output directory the
        runner recorded for ``run``, and hands them over explicitly. The runner
        itself does not use it, because at the time it builds a context the run
        has produced neither.
        """
        execution = ctx.execution
        return cls(
            plan=plan,
            run=run,
            state=RunState.of(ctx),
            store=store,
            model=execution.models_by_run_id.get(run.id),
            output_dir=execution.output_dirs_by_run_id.get(run.id),
            lumped_cache=execution.lumped_ram_cache,
        )


@dataclass(frozen=True)
class RunExecutionResult:
    """Payload returned by a solver adapter after one run completes.

    ``primary_model`` is the exact model produced by the run and is always
    recorded by the runner, which resolves it later for a run that declares
    this one in ``depends_on``.

    ``solver_output_dir`` is the directory where the solver wrote its raw
    output files (e.g. ``.hds``, ``.cbc``). May be ``None`` for in-memory
    solvers.

    ``metrics`` carries lightweight scalar execution metadata produced by
    the solver itself. It is intentionally optional so older/custom adapters
    can keep returning only a model and an output directory.
    """

    primary_model: Any
    solver_output_dir: Path | None = None
    metrics: Mapping[str, Any] = field(default_factory=dict)
