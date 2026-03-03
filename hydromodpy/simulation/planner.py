"""Build concrete process runs from declarative simulation config."""

from __future__ import annotations

from hydromodpy.simulation.config import SimulationConfig
from hydromodpy.simulation.plan import ProcessRun, SimulationPlan
from hydromodpy.solver.compatibility import required_bindings


class SimulationPlanner:
    """Resolves declarative processes into executable process-solver runs."""

    def build(self, config: SimulationConfig) -> SimulationPlan:
        """Validate *config* and return the ordered execution plan."""
        runs: list[ProcessRun] = []
        runs_by_capability: dict[tuple[str, str], list[ProcessRun]] = {}
        seen_process_ids: set[str] = set()
        seen_run_ids: set[str] = set()

        for index, process_cfg in enumerate(config.process, start=1):
            process_id = process_cfg.resolved_id(index)
            if process_id in seen_process_ids:
                raise ValueError(
                    f"Duplicate simulation process id '{process_id}'. "
                    "Each [[simulation.process]] entry must have a unique id."
                )
            seen_process_ids.add(process_id)

            for solver_name in process_cfg.solvers:
                dependencies: list[str] = []
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
                runs_by_capability.setdefault((process_cfg.type, solver_name), []).append(run)

        return SimulationPlan(
            name=config.name,
            description=config.description,
            runs=tuple(runs),
        )
