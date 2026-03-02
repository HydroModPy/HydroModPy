"""Phase 'flow': pre-process, run and post-process the flow solver."""

from __future__ import annotations

import os
import pickle
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from launcher.run_result import RunResult


def _run_flow(result: "RunResult") -> None:
    from hydromodpy.solver.modflow_nwt import (
        Modflow,
        ModflowPostprocessOptions,
        ModflowPreprocessOptions,
        ModflowRunOptions,
    )
    from hydromodpy.solver.modflow6 import Modflow6
    from hydromodpy.solver import SolverEngine

    cfg      = result.cfg
    settings = result.settings
    ws       = result.workspace

    preprocess_options = ModflowPreprocessOptions(
        box=settings.box,
        sink_fill=settings.sink_fill,
        check_grid=settings.check_grid,
        plot_cross=settings.plot_cross,
        cross_ylim=tuple(settings.cross_ylim) if settings.cross_ylim else None,
    )

    model_folder = ws.simulations_folder

    if cfg.solver.solver_engine == SolverEngine.MODFLOW_NWT:
        model_modflow = Modflow(
            result.geographic,
            model_folder=model_folder,
            model_name=settings.model_name,
            bin_path=ws.bin_path,
            modflow_config=cfg.modflownwt,
            preprocess_options=preprocess_options,
        )
    else:
        model_modflow = Modflow6(
            result.geographic,
            model_folder=model_folder,
            model_name=settings.model_name,
            bin_path=ws.bin_path,
            modflow_config=cfg.modflow6,
            preprocess_options=preprocess_options,
        )

    model_modflow.pre_processing(
        flow=result.flow,
        domain=result.domain,
        options=preprocess_options,
    )

    # Persist the pre-processed model object (mirrors example12 pickle pattern)
    pickle_file = os.path.join(
        ws.simulations_folder, settings.model_name,
        f"results_{settings.model_name}.pkl",
    )
    with open(pickle_file, "wb") as fh:
        pickle.dump(
            {"list_model_name": [settings.model_name],
             "list_model_modflow": [model_modflow]},
            fh,
        )

    success = model_modflow.processing(
        options=ModflowRunOptions(
            write_model=True,
            run_model=True,
            link_mt3dms=True,
        )
    )

    if success:
        model_modflow.post_processing(
            options=ModflowPostprocessOptions(
                watertable_elevation=True,
                seepage_areas=True,
                outflow_drain=True,
                accumulation_flux=True,
                watertable_depth=True,
                groundwater_flux=False,
                groundwater_storage=False,
                intermittency_weekly=False,
                intermittency_monthly=True,
                intermittency_yearly=False,
                export_all_tif=False,
            )
        )

    result.model_modflow = model_modflow
