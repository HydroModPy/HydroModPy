# -*- coding: utf-8 -*-
"""
Created on Thu Jan  8 15:42:45 2026

@author: pelissierm
"""

import logging
from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path


def run_pyhelp_simulation(run_pyhelp_func, workdir: Path, logger):
    workdir.mkdir(parents=True, exist_ok=True)
    logger.info(f"[pyhelp] running run_pyhelp(workdir={workdir})")

    buf = io.StringIO()

    prev_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL) 

    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            ret, diag = run_pyhelp_func(str(workdir))
    finally:
        logging.disable(prev_disable) 
    for line in buf.getvalue().splitlines():
        if line.strip():
            logger.info(f"[pyhelp.ext] {line}")

    logger.info(f"[pyhelp] return_code={ret} diag={diag}")
    return ret, diag



def run_pyhelp_plots(pyhelp_plots_module, workdir: Path, site_id: str, logger):
    plots_dir = workdir / "plots_pyhelp"
    plots_dir.mkdir(parents=True, exist_ok=True)

    pyhelp_plots_module.plot_all_outputs(str(workdir), save_dir=str(plots_dir))
    pyhelp_plots_module.plot_spatialised(
        csv_path=workdir / "help_example_yearly.csv",
        component="rechg",
        save_path=workdir / "plots_pyhelp" / "rechg_spatial.png",
        boundary_shp=workdir.parent / "results_stable" / "geographic" / "watershed.shp",
        glaciers_shp=Path(r"Z:\HDPY_database_forModelling\PyHELP_rasters\rgi_clip.shp"),
        dem_for_hillshade=r"Z:\HDPY_database_forModelling\pyHELP_rasters\dem_250m.tif"
    )


    logger.info(f"[pyhelp] plots -> {plots_dir}")








