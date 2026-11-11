"""MODFLOW 6 processing: write and run simulation."""

from __future__ import annotations

import os
import time
import warnings
from pathlib import Path

from hydromodpy.core.console import progress
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.interrupts import raise_if_stop_requested
from hydromodpy.model.initial.state import CyclicStart, SteadyStart
from hydromodpy.solver.modflow6.support.flopy_header_cache import install_flopy_header_cache
from hydromodpy.solver.modflow6.support.steady_initial_conditions import (
    apply_modflow6_cyclic_spinup_heads,
    apply_modflow6_cyclic_spinup_lakes,
    apply_modflow6_steady_state_initial_heads,
    is_auxiliary_folder,
    run_modflow6_cyclic_spinup,
    run_modflow6_steady_state_initialization,
)
from hydromodpy.solver.modflow6.support.windows_paths import check_mf6_workspace_paths
from hydromodpy.solver.modflow_common.options import ModflowRunOptions
from hydromodpy.solver.modflow_common.progress import (
    run_simulation_with_progress,
    write_listing_status,
)

logger = get_logger(__name__)


def written_input_files(folder: str | os.PathLike[str] | None) -> tuple[str, ...]:
    """Return every file under ``folder``, relative to it, in name order.

    The folders of the auxiliary steady solve and of the spin-up cycles are left
    out: they are models of their own, not inputs of the run. A folder that
    does not exist, and no folder, have no files.
    """
    if folder is None or not os.path.isdir(folder):
        return ()
    root = Path(folder)
    found: list[str] = []
    for current, folders, files in os.walk(root):
        folders[:] = sorted(name for name in folders if not is_auxiliary_folder(name))
        found.extend((Path(current) / name).relative_to(root).as_posix() for name in files)
    return tuple(sorted(found))


def run_processing(model, options: ModflowRunOptions | None = None) -> bool:
    """Write the simulation unless told not to, start it, and solve it. Returns success flag.

    A start from a steady solve or a spin-up runs its auxiliary model first and
    puts its heads in IC. Then the whole simulation is written, and the files
    under the folder of the model are listed in ``model.input_files``, before the
    solve writes any output. With ``write_model`` false the files on disk are the
    input, as after a rerun, and only an IC that a start changed is written.
    """
    install_flopy_header_cache()
    if options is None:
        options = ModflowRunOptions()
    elif not isinstance(options, ModflowRunOptions):
        raise TypeError("processing options must be ModflowRunOptions")

    steady_initial_heads_applied = False
    cycle_lakes_applied = False
    model.initial_state_converged = None
    inputs = model.inputs
    if (
        options.run_model
        and inputs.time.regime == "transient"
        and isinstance(inputs.initial, SteadyStart)
    ):
        with progress.status("Steady-state initialization"):
            steady_heads = run_modflow6_steady_state_initialization(
                model,
                verbose=bool(options.verbose),
            )
        apply_modflow6_steady_state_initial_heads(model, steady_heads)
        steady_initial_heads_applied = True

    if (
        options.run_model
        and inputs.time.regime == "transient"
        and isinstance(inputs.initial, CyclicStart)
    ):
        with progress.status("Cyclic spin-up"):
            heads, cycles, settled = run_modflow6_cyclic_spinup(
                model, verbose=bool(options.verbose)
            )
        apply_modflow6_cyclic_spinup_heads(model, heads)
        apply_modflow6_cyclic_spinup_lakes(model, cycles)
        cycle_lakes_applied = getattr(model, "lak", None) is not None
        steady_initial_heads_applied = True
        if settled:
            logger.info("Cyclic spin-up settled after %d cycle(s).", cycles)
        else:
            message = (
                f"the cyclic spin-up ran its {cycles} allowed cycle(s) without the head "
                "and the lake stages settling, and the run starts from the last one anyway. Raise "
                "flow.ic.max_cycles, or loosen flow.ic.tol_head, and say in the write-up "
                "that the antecedent state did not converge."
            )
            logger.warning(message)
            warnings.warn(message, RuntimeWarning, stacklevel=2)

    if options.write_model:
        with write_listing_status():
            model.sim.write_simulation(silent=False)
        model.input_files = written_input_files(getattr(model, "full_path", None))
    elif steady_initial_heads_applied:
        model.ic.write()
        if cycle_lakes_applied:
            model.lak.write()

    success_model = False
    model.last_flow_solve_time_seconds = None
    if options.run_model:
        check_mf6_workspace_paths(model.sim)
        solve_start = time.perf_counter()
        try:
            if getattr(options, "runner", "subprocess") == "api":
                success_model = _run_via_api(model, verbose=bool(options.verbose))
            else:
                success_model, _ = run_simulation_with_progress(model.sim, int(model.nper))
        finally:
            model.last_flow_solve_time_seconds = time.perf_counter() - solve_start
        if success_model:
            warn_on_throttled_wells(model)
    return success_model


def warn_on_throttled_wells(model) -> list[dict]:
    """Warn when AUTO_FLOW_REDUCE cut a well by more than 10 % of its requested volume.

    Compares the volume the WEL package was asked for with the one the budget
    file reports. The rows are kept on ``model.well_throttle_report`` and the
    pumped share on ``model.well_pumped_percent``, which the adapter hands to
    the run as a metric. A missing budget or well package returns an empty list.
    """
    from hydromodpy.model.sinks_sources.wells import (
        pumped_percent,
        throttled_well_message,
        throttled_well_report,
    )

    rows: list[dict] = []
    model.well_pumped_percent = None
    try:
        wel = getattr(model, "wel", None)
        if wel is None:
            model.well_throttle_report = rows
            return rows
        requested, applied = _well_volumes(model, wel)
        rows = throttled_well_report(requested, applied)
        model.well_pumped_percent = pumped_percent(requested, applied)
    except Exception as exc:  # the check must never fail a finished solve
        logger.warning("Well pumping check skipped: %s", exc)
    model.well_throttle_report = rows
    if rows:
        message = throttled_well_message(rows)
        logger.warning(message)
        warnings.warn(message, RuntimeWarning, stacklevel=2)
    return rows


def _well_volumes(model, wel) -> tuple[dict, dict]:
    """Return requested and applied well volumes (m3) keyed by ``(layer, cell)``."""
    import os

    import flopy
    import numpy as np

    folder = model.sim.simulation_data.mfpath.get_sim_path()
    cbc_path = os.path.join(folder, f"{model.model_output_name}.cbc")
    cbc = flopy.utils.CellBudgetFile(cbc_path, precision="double")
    times = [float(t) for t in cbc.get_times()]
    kstpkper = cbc.get_kstpkper()
    ncpl = int(model.gwf.modelgrid.ncpl)
    spd = wel.stress_period_data.get_data()
    requested: dict = {}
    applied: dict = {}
    previous = 0.0
    last_rows = None
    for totim, (_, kper) in zip(times, kstpkper, strict=False):
        dt = totim - previous
        previous = totim
        rows = spd.get(int(kper), last_rows)
        last_rows = rows
        if rows is None:
            continue
        for row in rows:
            layer, cell = (int(i) for i in row["cellid"][:2])
            key = (layer, cell)
            requested[key] = requested.get(key, 0.0) + float(row["q"]) * dt
        for record in cbc.get_data(totim=totim, text="WEL"):
            for item in np.atleast_1d(record):
                node = int(item["node"]) - 1
                key = (node // ncpl, node % ncpl)
                applied[key] = applied.get(key, 0.0) + float(item["q"]) * dt
    return requested, applied


def _warn_mf6_version_parity(lib_path: str, bin_path: object) -> None:
    """Warn once when the resolved libmf6 and the mf6 executable versions differ."""
    from pathlib import Path

    from hydromodpy.core.workspace.workspace import resolve_bin_path
    from hydromodpy.solver.modflow_common.binaries import (
        exe_filename,
        locate_solver_binary,
        warn_on_mf6_version_mismatch,
    )

    try:
        bindir = Path(bin_path or resolve_bin_path()).expanduser()
        exe = locate_solver_binary(bindir, "mf6") or (bindir / exe_filename("mf6"))
        warn_on_mf6_version_mismatch(exe, lib_path)
    except Exception:  # pragma: no cover - a version probe must never break a solve
        pass


def _stopping(callback, stop_flag):
    """Return ``callback`` composed with a read of ``stop_flag`` at the end of each time step.

    A flag on disk raises ``StopRequested``, a ``KeyboardInterrupt``, which the
    runner of libmf6 does not wrap in a solver error and finalizes the library
    on. The flag is read before ``callback``, so a stopped step does no more work.
    """
    from hydromodpy.solver.modflow6.api.api_runner import Mf6ApiContext, Mf6ApiStep

    def stop_then_call(ctx: Mf6ApiContext) -> None:
        if ctx.step is Mf6ApiStep.timestep_end:
            raise_if_stop_requested(stop_flag)
        callback(ctx)

    return stop_then_call


def _run_via_api(model, *, verbose: bool) -> bool:
    """Drive the already-written workspace through libmf6 instead of the exe.

    The simulation is written exactly as in the subprocess path, so the OC and
    LAK packages produce the same .hds/.cbc/obs/stage outputs the extractors
    read. Only the solve engine differs.

    The solve runs in this process, which keeps the live "Solving stress periods"
    progress bar. A parallel calibration gives each trial its own worker process,
    so each gets a private libmf6 instance. A developer callback attached as
    ``_mf6_api_callback`` replaces the exposed-band one, and ``_mf6_api_lib_path``
    overrides the library path.

    Whatever the callback is, it is composed with a read of the stop flag of the
    slot at the end of each time step, so a stop asked while the solve runs ends
    it between two steps. The executable path never reads the flag: FloPy reads
    the output of the child process, and an exception raised in its loop would
    leave the executable writing into a folder that a resume rewrites. The stop
    waits for the solve to end, and the runner of the plan reads the flag after.
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

    from hydromodpy.solver.modflow6.api.api_runner import Mf6ApiContext, run_mf6_api

    if callback is None:
        band_specs = getattr(model, "_exposed_band_runoff_specs", None)
        if band_specs:
            from hydromodpy.solver.modflow6.support.lake_band_runoff import (
                make_exposed_band_runoff_callback,
            )

            callback = make_exposed_band_runoff_callback(band_specs)
        else:

            def callback(ctx: Mf6ApiContext) -> None:
                return None

    stop_flag = getattr(getattr(model, "slot", None), "stop_flag", None)
    if stop_flag is not None:
        callback = _stopping(callback, stop_flag)
    return run_mf6_api(model.full_path, callback, lib_path=lib_path, verbose=verbose)
