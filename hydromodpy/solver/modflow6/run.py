"""MODFLOW 6 processing: write and run simulation."""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar

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
#
# Scoped through a ContextVar, not a module global: two overlapping calibration
# sessions in one process each get an independent binding, so one exiting can no
# longer flip the other back to in-process mid-run. Worker threads do NOT inherit
# a ContextVar automatically; the parallel engine propagates the caller's context
# to each worker (calibration.engine copies the context per task).
_api_isolation_var: ContextVar[bool] = ContextVar("hmp_api_isolation", default=False)

# A non-converging libmf6 solve can spin at full CPU indefinitely (the solve() call
# never returns), which would wedge a whole parallel calibration on one bad trial.
# The isolated child is killed after this wall-clock budget so the trial is recorded
# as failed and the session continues. Generous vs a normal daily solve (~15 min);
# override per model with ``[<backend>].mf6_api_timeout_s`` (a positive float).
_API_ISOLATION_DEFAULT_TIMEOUT_S = 2400.0


def _api_isolation_timeout_s(model) -> float | None:
    runtime = getattr(getattr(model, "modflow_config", None), "runtime", None)
    override = getattr(runtime, "mf6_api_timeout_s", None)
    if override is not None:
        return float(override)
    return _API_ISOLATION_DEFAULT_TIMEOUT_S


def _warn_mf6_version_parity(lib_path: str, bin_path: object) -> None:
    """Warn once when the resolved libmf6 and the mf6 executable versions differ."""
    from pathlib import Path

    from hydromodpy.solver.modflow_common.binaries import (
        exe_filename,
        locate_solver_binary,
        managed_bin_dir,
        warn_on_mf6_version_mismatch,
    )

    try:
        bindir = Path(bin_path).expanduser() if bin_path else managed_bin_dir()
        exe = locate_solver_binary(bindir, "mf6") or (bindir / exe_filename("mf6"))
        warn_on_mf6_version_mismatch(exe, lib_path)
    except Exception:  # pragma: no cover - a version probe must never break a solve
        pass


@contextmanager
def api_isolation_context(enabled: bool):
    """Isolate api solves in a spawn child process within this dynamic scope.

    The setting is context-local (a ContextVar), so overlapping sessions do not
    clobber each other and the token reset restores exactly the caller's prior
    value. Promotion (a single replay run) runs outside the scope and stays
    in-process.
    """
    token = _api_isolation_var.set(bool(enabled))
    try:
        yield
    finally:
        _api_isolation_var.reset(token)


def api_isolation_enabled() -> bool:
    """Return whether the current context isolates api solves in a child process."""
    return _api_isolation_var.get()


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
    from hydromodpy.solver.modflow_common.binaries import ensure_solver_library

    bin_path = getattr(model, "bin_path", None)
    lib_path = getattr(model, "_mf6_api_lib_path", None)
    if lib_path is None:
        # Resolve libmf6 with the model's bin_path (like the exe), so the api and
        # subprocess paths pull from the same directory.
        lib_path = str(ensure_solver_library("libmf6", bin_path=bin_path))
    _warn_mf6_version_parity(lib_path, bin_path)
    callback = getattr(model, "_mf6_api_callback", None)

    if callback is None and api_isolation_enabled():
        from hydromodpy.solver.modflow6.api_subprocess import run_mf6_api_isolated

        return run_mf6_api_isolated(
            model.full_path,
            band_specs=getattr(model, "_exposed_band_runoff_specs", None),
            lib_path=lib_path,
            timeout=_api_isolation_timeout_s(model),
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
