# %%
# -*- coding: utf-8 -*-

import argparse
import os
import os.path as osp
import sys
from pathlib import Path

repo_root = Path(r"C:\Users\Pelissierm\Hydromodpy")
sys.path.insert(0, str(repo_root))

import shutil
import time
import pandas as pd

from hydromodpy.pyhelp.managers import HelpManager
from hydromodpy.pyhelp import bilan as HelpBilan

from hydromodpy.pyhelp.monthly_output import save_monthly_climatology
from hydromodpy.pyhelp.daily_output import (
    calc_area_daily_avg,
    save_area_yearly_series_from_daily,
)


from hydromodpy.tools import get_logger

logger = get_logger(__name__)

def run_pyhelp(workdir: str) -> int:
    
    pyhelp_stat = 0

    logger.info("Running PyHELP in workdir: %s", workdir)
    logger.info("pyhelp.bilan module resolved at %s", HelpBilan.__file__)

    def run_help(path_to_precip: str,
                 path_to_airtemp: str,
                 path_to_solrad: str,
                 path_to_grid: str):
        
        helpm_local = HelpManager(
            workdir,
            path_to_grid=path_to_grid,
            path_to_precip=path_to_precip,
            path_to_airtemp=path_to_airtemp,
            path_to_solrad=path_to_solrad,
        )
    
        cellnames_local = helpm_local.grid.index[helpm_local.grid["Bassin"] == 1]
    
        output_help_local = helpm_local.calc_help_cells(
            path_to_hdf5=osp.join(workdir, "help_example.out"),
            cellnames=cellnames_local,
            tfsoil=-2,
            sf_edepth=1,
            sf_ulai=1,
            sf_cn=1,
        )
    
        output_help_local.save_to_csv(osp.join(workdir, "help_example_yearly.csv"))
        return helpm_local, cellnames_local, output_help_local


    precip_fixed  = osp.join(workdir, "precip_input_data_fixed.csv")
    precip_backup = osp.join(workdir, "precip_input_data_backup.csv")
    
    airtemp_fixed  = osp.join(workdir, "airtemp_input_data_fixed.csv")
    airtemp_backup = osp.join(workdir, "airtemp_input_data_backup.csv")
    
    solrad_fixed  = osp.join(workdir, "solrad_input_data_fixed.csv")
    solrad_backup = osp.join(workdir, "solrad_input_data_backup.csv")
    
    grid_normal = osp.join(workdir, "input_grid.csv")
    
    try:
        helpm, cellnames, output_help = run_help(
            precip_fixed,
            airtemp_fixed,
            solrad_fixed,
            grid_normal,
        )
    
    except ValueError as e1:
        print("using homogeneous climatic inputs :", e1)
        time.sleep(60)
        pyhelp_stat = 1

        helpm, cellnames, output_help = run_help(
            precip_backup,
            airtemp_backup,
            solrad_backup,
            grid_normal,
        )
        
    output_help.save_to_csv(osp.join(workdir, "help_example_yearly.csv"))

    # Plot some results
    default_output_dir = os.path.join(workdir, "plots_pyhelp")
    
    try:
        output_help.plot_area_monthly_avg(
            fig_title="PyHELP Example",
            figname=osp.join(default_output_dir, "area_monthly_avg.png"),
        )

        output_help.plot_area_yearly_avg(
            fig_title="PyHELP Example",
            figname=osp.join(default_output_dir, "area_yearly_avg.png"),
        )

        output_help.plot_area_yearly_series(
            fig_title="PyHELP Example",
            figname=osp.join(default_output_dir, "area_yearly_series.png"),
        )
    except AttributeError as e:
        logger.warning("PyHELP built-in plots failed (Matplotlib API change): %s", e)
        
    # =========================================================================
    # Compare with river total and base streamflow
    # =========================================================================
    output_surf = helpm.calc_surf_water_cells(
        cellnames=cellnames,
        evp_surf=650,
        path_outfile=osp.join(workdir, "surf_example.out"),
    )

    # =========================================================================
    # monthly analysis
    # =========================================================================
    print("[INFO] Calculating daily components")
    df_daily_mean = calc_area_daily_avg(cellnames, helpm.workdir)
    df_daily_mean.to_csv(osp.join(workdir, "help_example_daily_mean.csv"))
    
    temp_dir = osp.join(helpm.workdir, "help_input_files", ".temp")
    out_paths = list(Path(temp_dir).glob("*.OUT"))
    
    cellnames_str = set(map(str, cellnames))
    cell_outfiles = {}
    for p in out_paths:
        cid = p.stem
        if cid in cellnames_str:
            cell_outfiles[cid] = str(p)
    
    if not cell_outfiles:
        raise RuntimeError("Aucun fichier .OUT trouvé/matché pour les pixels dans .temp")
    
    # 1) climatologie mensuelle (par pixel)
    save_monthly_climatology(
        cell_outfiles=cell_outfiles,
        out_csv=osp.join(workdir, "help_example_monthly_climatology_from_daily.csv"),
        year_from=-float("inf"),
        year_to=float("inf"),
        require_full_years=True,
        output_format="wide",
    )
    
    # 2) série annuelle de zone (pour interannual + trend plots)
    save_area_yearly_series_from_daily(
        cell_outfiles=cell_outfiles,
        out_csv=osp.join(workdir, "help_example_area_yearly_series_from_daily.csv"),
        year_from=-float("inf"),
        year_to=float("inf"),
    )
    
    
    shutil.rmtree(
        osp.join(helpm.workdir, "help_input_files", ".temp"), ignore_errors=True
    )

    return 0, pyhelp_stat



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run PyHELP example workflow.")
    parser.add_argument(
        "--workdir",
        help="Working directory containing HELP inputs (defaults to PYHELP_WORKDIR env var).",
        default=None,
    )
    args = parser.parse_args()

    workdir = args.workdir or os.getenv("PYHELP_WORKDIR")
    if not workdir:
        raise RuntimeError(
            "Working directory missing; set PYHELP_WORKDIR or pass --workdir."
        )

    run_pyhelp(workdir)