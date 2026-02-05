# -*- coding: utf-8 -*-

import argparse
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Union
import time

import pandas as pd

from hydromodpy.pyhelp.managers import HelpManager
from hydromodpy.pyhelp import bilan as HelpBilan
from hydromodpy.pyhelp.daily_output import (
    calc_area_daily_avg,
    save_cells_monthly_climatology_from_daily,
)
from hydromodpy.tools import get_logger

logger = get_logger(__name__)


#%% Configuration
@dataclass(frozen=True)
class ClimateInputs:
    precip: Path
    airtemp: Path
    solrad: Path


@dataclass(frozen=True)
class WorkflowFiles:
    workdir: Path
    grid: Path
    climate_input: ClimateInputs
    climate_backup: Optional[ClimateInputs] = None

    @staticmethod
    def from_workdir(workdir: Union[str, Path], climate_map: dict = {}):
        wd = Path(workdir)
        if not wd.exists():
            raise FileNotFoundError(f"workdir not found: {wd}")

        grid = wd / "input_grid.csv"
        if not grid.exists():
            raise FileNotFoundError(f"Missing grid file: {grid}")
        
        # define default climate candidate following classic work flow
        climate_candidate = ClimateInputs(
                    precip= wd / "precip_input_data.csv",
                    airtemp= wd / "airtemp_input_data.csv",
                    solrad= wd / "solrad_input_data.csv",
                )
        if climate_map:
            try:
                climate_candidate = ClimateInputs(
                    precip= climate_map["precip_input"],
                    airtemp=climate_map["airtemp_input"],
                    solrad=climate_map["solrad_input"],
                )
            except Exception:
                logger.exception("Invalid climate input map provided.")

        for p in (climate_candidate.precip, climate_candidate.airtemp, climate_candidate.solrad):
            if not p.exists():
                raise FileNotFoundError(f"Missing climate input: {p}")

        backup_candidate = ClimateInputs(
            precip=wd / "precip_input_data_backup.csv",
            airtemp=wd / "airtemp_input_data_backup.csv",
            solrad=wd / "solrad_input_data_backup.csv",
        )
        backup = (
            backup_candidate
            if all(p.exists() for p in (backup_candidate.precip, backup_candidate.airtemp, backup_candidate.solrad))
            else None
        )
        return WorkflowFiles(workdir=wd, grid=grid, climate_input=climate_candidate, climate_backup=backup)


def _plots_dir(workdir):
    p = workdir / "plots_pyhelp"
    p.mkdir(parents=True, exist_ok=True)
    return p

def _temp_out_dir(workdir):
    return workdir / "help_input_files" / ".temp"

def build_cell_outfiles(temp_dir, cellnames):
    temp_dir = Path(temp_dir)
    if not temp_dir.exists():
        logger.warning("Temp dir not found: %s", temp_dir)
        return {}

    wanted = set(map(str, cellnames))
    outfiles: Dict[str, str] = {}
    for p in temp_dir.glob("*.OUT"):
        cid = p.stem
        if cid in wanted:
            outfiles[cid] = str(p)
    return outfiles

def _run_help_once(workdir, grid, climate):

    helpm = HelpManager(
        str(workdir),
        path_to_grid=str(grid),
        path_to_precip=str(climate.precip),
        path_to_airtemp=str(climate.airtemp),
        path_to_solrad=str(climate.solrad),
    )

    cellnames = helpm.grid.index[helpm.grid["Bassin"] == 1]

    output_help = helpm.calc_help_cells(
        path_to_hdf5=str(workdir / "help_example.out"),
        cellnames=cellnames,
        tfsoil=-2,
        sf_edepth=1,
        sf_ulai=1,
        sf_cn=1,
    )

    return helpm, cellnames, output_help

def _builtin_plots(output_help, out_dir):
    try:
        output_help.plot_area_monthly_avg(
            fig_title="PyHELP Example",
            figname=str(out_dir / "area_monthly_avg.png"),
        )
        output_help.plot_area_yearly_avg(
            fig_title="PyHELP Example",
            figname=str(out_dir / "area_yearly_avg.png"),
        )
        output_help.plot_area_yearly_series(
            fig_title="PyHELP Example",
            figname=str(out_dir / "area_yearly_series.png"),
        )
    except AttributeError as e:
        logger.warning("PyHELP built-in plots failed (Matplotlib/API change): %s", e)
    except Exception:
        logger.exception("PyHELP built-in plots failed unexpectedly.")


def run_pyhelp(workdir, climate_map: dict = {}):

    files = WorkflowFiles.from_workdir(workdir, climate_map = climate_map)
    used_backup = 0


    logger.info("Running PyHELP in workdir: %s", files.workdir)
    logger.info("pyhelp.bilan module resolved at %s", getattr(HelpBilan, "__file__", "unknown"))

    # Run HELP (with fallback to backup climate inputs if fixed fails)
    try:
        helpm, cellnames, output_help = _run_help_once(files.workdir, files.grid, files.climate_input)
    except ValueError as e:
        if files.climate_backup is None:
            raise
        logger.warning("Fixed climate inputs failed (%s). Falling back to backup climate inputs.", e)
        time.sleep(300)
        used_backup = 1
        helpm, cellnames, output_help = _run_help_once(files.workdir, files.grid, files.climate_backup)

    # Export yearly outputs
    yearly_csv = files.workdir / "help_example_yearly.csv"
    output_help.save_to_csv(str(yearly_csv))
    logger.info("Saved yearly outputs: %s", yearly_csv)

    # built-in plots
    plot_dir = _plots_dir(files.workdir)
    _builtin_plots(output_help, plot_dir)

    # Surface water calc
    _ = helpm.calc_surf_water_cells(
        cellnames=cellnames,
        evp_surf=650,
        path_outfile=str(files.workdir / "surf_example.out"),
    )

    #Daily analysis
    logger.info("Calculating daily components (area mean)")
    df_daily_mean = calc_area_daily_avg(cellnames, helpm.workdir)

    # Build area yearly series from daily mean (mm/year)
    df_area_yearly = (
        df_daily_mean.groupby(df_daily_mean.index.year)
        .sum(numeric_only=True)
        .reset_index()
        .rename(columns={df_daily_mean.index.name or "index": "year"})
    )
    df_area_yearly = df_area_yearly.rename(columns={df_area_yearly.columns[0]: "year"})

    out_area_yearly = files.workdir / "help_example_area_yearly_series_from_daily.csv"
    df_area_yearly.to_csv(out_area_yearly, index=False, encoding="utf-8")
    logger.info("Saved area yearly series from daily: %s", out_area_yearly)

    # Monthly climatology per cell
    temp_dir = _temp_out_dir(files.workdir)
    cell_outfiles = build_cell_outfiles(temp_dir, cellnames)

    if not cell_outfiles:
        logger.warning("No *.OUT files found for selected cells in %s. Skipping monthly climatology export.", temp_dir)
    else:
        out_clim = files.workdir / "help_example_monthly_climatology_from_daily.csv"
        save_cells_monthly_climatology_from_daily(
            cell_outfiles=cell_outfiles,
            out_csv=str(out_clim),
            year_from=-float("inf"),
            year_to=float("inf"),
            require_full_years=True,
            output_format="wide",
        )
        logger.info("Saved monthly climatology from daily: %s", out_clim)

    # Cleanup temp dir
    shutil.rmtree(temp_dir, ignore_errors=True)

    return 0, used_backup


def _parse_args():
    parser = argparse.ArgumentParser(description="Run PyHELP example workflow.")
    parser.add_argument("--workdir",default=None,
        help="Working directory containing HELP inputs (defaults to PYHELP_WORKDIR env var).",
    )
    return parser.parse_args()


def main():
    args = _parse_args()
    workdir = args.workdir or os.getenv("PYHELP_WORKDIR")
    if not workdir:
        raise RuntimeError("Working directory missing; set PYHELP_WORKDIR or pass --workdir.")

    exit_code, used_backup = run_pyhelp(workdir)
    logger.info("Workflow completed (used_backup_inputs=%s)", used_backup)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
