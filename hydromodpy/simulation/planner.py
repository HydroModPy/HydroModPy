"""Translate declarative simulation config into an executable simulation plan.

The planner is the boundary between "what the user requested" and "what the
runner can execute". The input ``SimulationConfig`` stays declarative:
a process may list several solvers, and dependencies are only implied by
process/solver compatibility rules.

This module normalizes that into a flat ordered list of ``ProcessRun`` objects
with explicit backward dependencies and a deterministic order. It deliberately
does not reorder anything: the user-declared order is kept, and the planner
simply validates that every required dependency is already provided by an
earlier run.
"""

from __future__ import annotations

from hydromodpy.simulation.config import SimulationConfig
from hydromodpy.simulation.plan import ProcessRun, SimulationPlan
from hydromodpy.solver.compatibility import required_bindings


class SimulationPlanner:
    """Expand and validate simulation config into concrete runnable units."""

    def build(self, config: SimulationConfig) -> SimulationPlan:
        """Expand ``config`` into a validated ordered ``SimulationPlan``.

        The planner performs four key tasks:

        - expand one process entry into one ``ProcessRun`` per solver,
        - verify uniqueness of both process ids and concrete run ids,
        - resolve each required dependency to a previously planned run.
        """
        runs: list[ProcessRun] = []
        # Track the latest run that provides each (process_type, solver)
        # capability so dependent runs can bind to a concrete upstream model.
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
                # only depend on capabilities already planned earlier.
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
                    # When several earlier runs provide the same capability, the
                    # most recent one is the one that will feed this run.
                    dependencies.append(providers[-1].id)

                # Concrete run ids distinguish solver variants originating from
                # the same declarative process entry.
                run_id = f"{process_id}::{solver_name}"
                if run_id in seen_run_ids:
                    raise ValueError(
                        f"Duplicate process run id '{run_id}'. "
                        "Check process ids and solver names."
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
