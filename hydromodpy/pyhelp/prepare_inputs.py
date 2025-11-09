# -*- coding: utf-8 -*-
"""
Created on Wed Jun  4 10:49:43 2025

@author: mathi
"""

"""
Fabrique input_grid.csv + 3 CSV climatiques PyHELP dans outdir.
Toutes les valeurs de porosité (poro1) et Ksat (ksat1) proviennent
directement de l'objet HydroModPy.
"""

from pathlib import Path
import shutil
from .pyhelp_grid    import PyhelpGrid
from .pyhelp_era5 import PyhelpEra5


def make_pyhelp_inputs(grid_base, dem, shp,
                       outdir, porosity, ksat,
                       *, era5_folder=None, ready_csvs=None):

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    grid_csv = outdir / "input_grid.csv"
    PyhelpGrid(grid_base, grid_csv, dem) \
        .update_parameters(poro1=porosity, ksat1=ksat)

    if era5_folder and ready_csvs:
        raise ValueError("Spécifiez soit era5_folder, soit ready_csvs, pas les deux")

    if era5_folder:
        era5_folder = Path(era5_folder)
        PyhelpEra5(str(era5_folder), shp).extract_era5_daily_timeseries()

        for fname in ("precip_input_data.csv",
                      "airtemp_input_data.csv",
                      "solrad_input_data.csv"):
            shutil.copy2(era5_folder / fname, outdir / fname)

    elif ready_csvs:
        precip_csv, tair_csv, solrad_csv = ready_csvs
        shutil.copy2(precip_csv, outdir / "precip_input_data.csv")
        shutil.copy2(tair_csv,    outdir / "airtemp_input_data.csv")
        shutil.copy2(solrad_csv,  outdir / "solrad_input_data.csv")

    else:
        raise ValueError("Vous devez fournir era5_folder OU ready_csvs")

    return grid_csv
