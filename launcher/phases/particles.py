"""Phase 'particles': run MODPATH particle tracking (NWT only)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from launcher.run_result import RunResult


def _run_particles(result: "RunResult") -> None:
    from hydromodpy.solver import SolverEngine
    from hydromodpy.solver.modflow_nwt import Modpath

    if result.cfg.solver.solver_engine != SolverEngine.MODFLOW_NWT:
        print(
            "MODPATH is only available with solver_engine='nwt'. "
            "Skipping particles phase."
        )
        return

    if result.model_modflow is None:
        raise RuntimeError(
            "Phase 'particles' requires 'flow' to have run first "
            "(result.model_modflow is None)."
        )

    ws            = result.workspace
    model_modflow = result.model_modflow

    model_modpath = Modpath(
        result.domain,
        result.transport,
        model_modflow,
        model_folder=ws.simulations_folder,
        model_name=model_modflow.model_name,
        bin_path=ws.bin_path,
    )

    model_modpath.pre_processing()

    model_modpath.processing(write_model=True, run_model=True)

    model_modpath.post_processing(
        model_modpath,
        ending_point=True,
        starting_point=True,
        pathlines_shp=True,
        particles_shp=True,
        random_id=None,
    )

    model_modpath.filt_processing(
        model_modpath,
        norm_flux=True,
        filt_time=True,
        filt_seep=True,
        filt_inout=True,
        calc_rtd=False,
        random_id=None,
    )

    result.model_modpath = model_modpath
