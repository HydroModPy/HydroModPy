"""Translate declarative simulation config into an executable simulation plan.

The planner is the boundary between "what the user requested" and "what the
runner can execute". The input ``SimulationConfig`` stays declarative, but it
is now intentionally constrained:

- at most one ``flow`` process,
- at most one ``transport`` process,
- one process can still list several solvers.

This module normalizes that into a flat ordered list of ``ProcessRun`` objects
with explicit backward dependencies and a deterministic order. The planner
deliberately does not reorder anything: the user-declared order is kept, and it
simply validates that every required dependency is already provided by an
earlier run.
"""

from __future__ import annotations

from hydromodpy.simulation.planning.config import SimulationConfig
from hydromodpy.simulation.planning.plan import ProcessRun, SimulationPlan
from hydromodpy.solver.compatibility import required_bindings


class SimulationPlanner:
    """Validate simulation config and emit concrete runnable units."""

    def build(self, config: SimulationConfig) -> SimulationPlan:
        """Convert ``config`` into a validated ordered ``SimulationPlan``.

        The planner performs four key tasks:

        - preserve the user-declared process order instead of re-sorting runs,
        - expand one process entry into one ``ProcessRun`` per solver,
        - verify uniqueness of both process ids and concrete run ids,
        - resolve each required dependency to a previously planned run.

        Example
        -------
        If the user declares:

        - ``flow_main`` with ``solvers=["modflownwt"]``
        - ``transport_main`` with ``solvers=["modpath", "mt3dms"]``

        then the planner emits three ordered runs:

        - ``flow_main::modflownwt``
        - ``transport_main::modpath``
        - ``transport_main::mt3dms``

        and each transport run is bound to the earlier compatible flow run
        required by the solver compatibility rules.
        """
        runs: list[ProcessRun] = []
        # Track the produced runs for each (process_type, solver) capability so
        # later runs can bind to the most recent compatible provider.
        runs_by_capability: dict[tuple[str, str], list[ProcessRun]] = {}
        # Separate guards keep TOML-level ids and concrete process/solver ids
        # unique, which produces clearer error messages.
        seen_process_ids: set[str] = set()
        seen_run_ids: set[str] = set()

        for process_cfg in config.process:
            process_id = process_cfg.id
            if process_id in seen_process_ids:
                raise ValueError(
                    f"Duplicate simulation process id '{process_id}'. "
                    "Each [[simulation.process]] entry must have a unique id."
                )
            seen_process_ids.add(process_id)

            for solver_name in process_cfg.solvers:
                dependencies: list[str] = []
                # Dependency resolution is strictly backward-looking: a run may
                # only depend on capabilities already planned earlier. If
                # ``transport_main::mt3dms`` appears before any compatible
                # ``flow::*`` provider, planning fails instead of reordering.
                for required_type, required_solver in required_bindings(
                    process_cfg.type, solver_name
                ):
                    providers = runs_by_capability.get((required_type, required_solver), [])
                    if not providers:
                        raise ValueError(
                            "Simulation process "
                            f"'{process_id}' ({process_cfg.type}/{solver_name}) "
                            "requires an earlier process using "
                            f"{required_type}/{required_solver}."
                        )
                    dependencies.append(providers[-1].id)

                run_id = f"{process_id}::{solver_name}"
                if run_id in seen_run_ids:
                    raise ValueError(
                        f"Duplicate process run id '{run_id}'. Check process ids and solver names."
                    )
                seen_run_ids.add(run_id)

                run = ProcessRun(
                    id=run_id,
                    process_id=process_id,
                    process_type=process_cfg.type,
                    solver=solver_name,
                    depends_on=tuple(dependencies),
                )
                runs.append(run)
                # Register the produced capability after the run is created so
                # later entries can depend on this exact run id.
                runs_by_capability.setdefault((process_cfg.type, solver_name), []).append(run)

        return SimulationPlan(
            name=config.name,
            description=config.description,
            runs=tuple(runs),
        )
