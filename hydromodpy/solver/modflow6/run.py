"""MODFLOW 6 processing: write and run simulation."""

from __future__ import annotations

import time

from hydromodpy.solver.modflow6.steady_initial_conditions import (
    apply_modflow6_steady_state_initial_heads,
    flow_uses_steady_state_initial_condition,
    run_modflow6_steady_state_initialization,
)
from hydromodpy.solver.modflow_common import ModflowRunOptions


def run_processing(model, options: ModflowRunOptions | None = None) -> bool:
    """Write packages and run the MODFLOW 6 simulation. Returns success flag."""
    if options is None:
        options = ModflowRunOptions()
    elif not isinstance(options, ModflowRunOptions):
        raise TypeError("processing options must be ModflowRunOptions")

    steady_initial_heads_applied = False
    if (
        options.run_model
        and getattr(model, "flow_regime", None) == "transient"
        and flow_uses_steady_state_initial_condition(getattr(model, "flow", None))
    ):
        steady_heads = run_modflow6_steady_state_initialization(
            model,
            verbose=bool(options.verbose),
        )
        apply_modflow6_steady_state_initial_heads(model, steady_heads)
        steady_initial_heads_applied = True

    if options.write_model:
        dirty_packages = tuple(getattr(model, "_runtime_dirty_packages", ()) or ())
        if dirty_packages:
            for package_name in dirty_packages:
                package = getattr(model, str(package_name), None)
                if package is None:
                    continue
                package.write()
            if steady_initial_heads_applied:
                model.ic.write()
            model._runtime_dirty_packages = ()
        else:
            model.sim.write_simulation(silent=not options.verbose)
    elif steady_initial_heads_applied:
        model.ic.write()

    success_model = False
    model.last_flow_solve_time_seconds = None
    if options.run_model:
        solve_start = time.perf_counter()
        try:
            success_model, _ = model.sim.run_simulation(silent=not options.verbose)
        finally:
            model.last_flow_solve_time_seconds = time.perf_counter() - solve_start
    return success_model
