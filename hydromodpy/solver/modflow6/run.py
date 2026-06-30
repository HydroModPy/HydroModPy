"""MODFLOW 6 processing: write and run simulation."""

from __future__ import annotations

import time
from contextlib import contextmanager

from hydromodpy.core import progress
from hydromodpy.solver.modflow6.flopy_header_cache import install_flopy_header_cache
from hydromodpy.solver.modflow6.steady_initial_conditions import (
    apply_modflow6_steady_state_initial_heads,
    flow_uses_steady_state_initial_condition,
    run_modflow6_steady_state_initialization,
)
from hydromodpy.solver.modflow_common import ModflowRunOptions
from hydromodpy.solver.modflow_common.progress import (
    run_simulation_with_progress,
    write_listing_status,
)


def run_processing(model, options: ModflowRunOptions | None = None) -> bool:
    """Write packages and run the MODFLOW 6 simulation. Returns success flag."""
    install_flopy_header_cache()
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
        with progress.status("Steady-state initialization"):
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
            with write_listing_status():
                model.sim.write_simulation(silent=False)
    elif steady_initial_heads_applied:
        model.ic.write()

    success_model = False
    model.last_flow_solve_time_seconds = None
    if options.run_model:
        solve_start = time.perf_counter()
        try:
            if getattr(options, "runner", "subprocess") == "api":
                success_model = _run_via_api(model, verbose=bool(options.verbose))
            else:
                success_model, _ = run_simulation_with_progress(model.sim, int(model.nper))
        finally:
            model.last_flow_solve_time_seconds = time.perf_counter() - solve_start
    return success_model


# Process-isolation toggle for the in-process API runner. libmf6 holds global
# Fortran state, so concurrent in-process solves (calibration threads) corrupt
# each other. The parallel calibration loop turns this on (api_isolation_context)
# so each thread's api solve runs in its own spawn child process; single runs and
# the promotion replay leave it off, keeping the in-process live progress bar and
# avoiding a per-solve process spawn.
_API_ISOLATION_ENABLED = False


def api_isolation_enabled() -> bool:
    """Whether api solves should run in an isolated child process."""
    return _API_ISOLATION_ENABLED


@contextmanager
def api_isolation_context(enabled: bool):
    """Isolate api solves in a spawn child process within this block when enabled.

    Restores the previous setting on exit, so promotion (a single replay run)
    after a parallel session is back on the in-process path.
    """
    global _API_ISOLATION_ENABLED
    previous = _API_ISOLATION_ENABLED
    _API_ISOLATION_ENABLED = bool(enabled)
    try:
        yield
    finally:
        _API_ISOLATION_ENABLED = previous


def _run_via_api(model, *, verbose: bool) -> bool:
    """Drive the already-written workspace through libmf6 instead of the exe.

    The simulation is written exactly as in the subprocess path, so the OC and
    LAK packages produce the same .hds/.cbc/obs/stage outputs the extractors
    read. Only the solve engine differs.

    The solve runs IN-PROCESS by default (keeping the live "Solving stress
    periods" progress bar and avoiding a process spawn). Under a parallel
    calibration session (:func:`api_isolation_context`) the production solve
    instead runs in a dedicated ``spawn`` child process so concurrent threads
    each get a private libmf6 instance; the exposed-band callback is rebuilt in
    the child from the picklable specs.

    A custom, non-serializable developer callback attached as
    ``_mf6_api_callback`` always stays IN-PROCESS (it cannot cross the process
    boundary); ``_mf6_api_lib_path`` overrides the library path on either path.
    """
    lib_path = getattr(model, "_mf6_api_lib_path", None)
    callback = getattr(model, "_mf6_api_callback", None)

    if callback is None and _API_ISOLATION_ENABLED:
        from hydromodpy.solver.modflow6.api_subprocess import run_mf6_api_isolated

        return run_mf6_api_isolated(
            model.full_path,
            band_specs=getattr(model, "_exposed_band_runoff_specs", None),
            lib_path=lib_path,
            verbose=verbose,
        )

    from hydromodpy.solver.modflow6.api_runner import Mf6ApiContext, run_mf6_api

    if callback is None:
        band_specs = getattr(model, "_exposed_band_runoff_specs", None)
        if band_specs:
            from hydromodpy.solver.modflow6.lake_band_runoff import (
                make_exposed_band_runoff_callback,
            )

            callback = make_exposed_band_runoff_callback(band_specs)
        else:

            def callback(ctx: Mf6ApiContext) -> None:
                return None

    return run_mf6_api(model.full_path, callback, lib_path=lib_path, verbose=verbose)
