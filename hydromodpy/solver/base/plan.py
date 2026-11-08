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

``RunSlot``, ``SolverRun`` and ``RunContext`` live here so that the runner,
the adapter Protocol and the adapters share one import source without a cycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from hydromodpy.core.contracts.solver_model import SolverModel
from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.core.state.run_state import RunState


@dataclass(frozen=True)
class ProcessRun:
    """One concrete execution unit produced by the planner.

    A single declarative ``[[simulation.process]]`` entry can expand to several
    ``ProcessRun`` objects when multiple solvers are listed. ``depends_on``
    stores resolved run identifiers, so the runner can hand over the exact
    upstream run that must already exist.
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


def _optional_path(value: Any) -> Path | None:
    return None if value is None else Path(value)


@dataclass(frozen=True, slots=True)
class RunSlot:
    """Where and how one run solves, filled by the runner of the plan, never by an adapter.

    ``folder`` is the root the backend creates the run folder in, and ``name``
    the run name, so the run writes into ``directory``, ``folder / name``. A
    backend that needs a safer file name (NWT) derives it from ``name``.
    ``stop_before_solve`` builds the model and solves nothing: the runner does
    not call ``run``. ``bin_dir`` is the folder of the solver binaries, or
    ``None`` for the managed cache. ``shared_forcing_dir`` is the folder a
    calibration trial keeps its forcing files in, apart from its model folder,
    or ``None`` to keep them beside the model.

    The folder and the binaries are facts of the machine, kept out of the
    ``Model`` and out of the options so that two runs of one model can solve in
    two places.
    """

    folder: Path
    name: str
    stop_before_solve: bool = False
    bin_dir: Path | None = None
    shared_forcing_dir: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "folder", Path(self.folder))
        object.__setattr__(self, "bin_dir", _optional_path(self.bin_dir))
        object.__setattr__(self, "shared_forcing_dir", _optional_path(self.shared_forcing_dir))
        if not str(self.name).strip():
            raise SolverInputError("RunSlot.name is the run name and cannot be blank.")

    @property
    def directory(self) -> Path:
        """The folder this run writes into, ``folder / name``."""
        return self.folder / self.name


@dataclass(frozen=True, kw_only=True)
class SolverRun:
    """What ``build``, ``run`` and ``rerun`` of a solver adapter return, one value for all three.

    ``model`` is the frozen ``hydromodpy.model.model.Model`` the run is built
    from, the model of its flow for a transport. ``options`` is the validated
    table of the backend, ``cfg.solver.options_of(name)``, or ``None`` for a
    backend that reads none. ``slot`` is where it solves.

    ``solver_model`` is the object the adapter built, read by a transport that
    follows the flow and by the observables of a calibration trial. It is
    ``None`` for a mesh run, which produces no model, after a resume past the
    solver, and once the derive step releases it.

    ``output_dir`` is the folder the solver wrote its raw files in (``.hds``,
    ``.cbc``), set by ``run``. ``input_files`` lists the input files ``run``
    wrote, relative to the run folder, which ``rerun`` copies. ``written`` says
    the input files are on disk, so ``run`` does not write them again.
    ``solved`` says the solve ran.

    ``metrics`` carries execution metadata the run produced about itself. The
    catalog only persists what converts to a finite float and skips the rest,
    which is why a mesh run can put its nested build summary here.

    ``initial_state_converged`` says whether the permanent solve that gave a flow
    run its starting state converged. ``None`` is a run that did not start from
    such a solve, which is every run but a flow run with a steady start. It is not
    in ``metrics`` because the catalog stores what is there and a new row would
    change the table of every run. The runner reads it before it starts a
    transport run that follows the flow, and refuses when it is ``False``.
    """

    slot: RunSlot
    model: Any = None
    options: BaseModel | None = None
    solver_model: SolverModel | None = None
    output_dir: Path | None = None
    input_files: tuple[str, ...] = ()
    written: bool = False
    solved: bool = False
    metrics: Mapping[str, Any] = field(default_factory=dict)
    initial_state_converged: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.slot, RunSlot):
            raise TypeError(f"SolverRun.slot is a RunSlot, got {type(self.slot).__name__}.")
        object.__setattr__(self, "output_dir", _optional_path(self.output_dir))
        object.__setattr__(self, "input_files", tuple(str(name) for name in self.input_files))


@dataclass(frozen=True)
class RunContext:
    """Resolved runtime context of one run, beside its ``Model``, options and slot.

    By the time a run receives this object, the planner has fixed the run order
    and the runner has resolved the upstream runs named in ``run.depends_on``,
    in ``upstream``, in that order.

    ``state`` is the reduced view of the workflow runtime
    (:class:`hydromodpy.core.state.run_state.RunState`), never the workflow
    context itself. A flow adapter reads neither ``state`` nor ``store``: its
    ``build`` reads the ``Model``, the options and the slot it is handed. A
    transport adapter reads ``state`` until the transport port takes the
    ``Model``.

    ``store`` is the catalog handle of the enclosing run, or ``None`` when the
    run writes no index (a calibration trial). It is a borrowed handle whose
    owner closes it, and nothing keeps a reference past the call.

    ``solver_run`` is what *this* run produced. It is ``None`` while the run
    builds and solves, and set on the contexts built after it completed,
    through ``RunContext.of``.
    """

    plan: SimulationPlan
    run: ProcessRun
    state: RunState
    store: Any = None
    solver_run: SolverRun | None = None
    upstream: tuple[SolverRun, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.state, RunState):
            raise TypeError(
                "RunContext.state must be a RunState view of the workflow runtime, "
                f"got {type(self.state).__name__}."
            )
        object.__setattr__(self, "upstream", tuple(self.upstream))

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
        solver: it reads the ``SolverRun`` the runner recorded for ``run`` in
        ``execution.solver_runs`` and hands it over explicitly. The runner
        itself does not use it, because at the time it builds a context the run
        has produced nothing.
        """
        return cls(
            plan=plan,
            run=run,
            state=RunState.of(ctx),
            store=store,
            solver_run=ctx.execution.solver_runs.get(run.id),
        )


# Key a backend writes into ``SolverRun.metrics`` for the final
# water-budget PERCENT DISCREPANCY, in percent. Any backend may write it;
# readers of ``metrics`` should not assume it comes from MODFLOW.
WATER_BUDGET_METRIC = "water_budget_percent_discrepancy"

# Key for the worst PERCENT DISCREPANCY over every time step of the model volume
# budget, in percent and signed. A calibration gate reads this one: a run that
# loses its balance in the middle and recovers at the end still has to be seen.
WATER_BUDGET_WORST_METRIC = "water_budget_worst_percent_discrepancy"
