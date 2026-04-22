# -*- coding: utf-8 -*-
"""
Created on Tue Apr 14 11:01:15 2026

@author: pelissierm
"""

import io
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import sys

sys.path.append(str('C:/Users/Pelissierm/Hydromodpy'))

from hydromodpy.pyhelp.managers import HelpManager
from hydromodpy.pyhelp.daily_output import calc_area_daily_avg


# INPUT RESOLUTION
def _resolve_climate_file(workdir: Path, var: str):
    debiased = workdir / f"{var}_input_data_debiased.csv"
    base = workdir / f"{var}_input_data.csv"

    if debiased.exists():
        return debiased, "debiased"
    if base.exists():
        return base, "base"

    raise FileNotFoundError(
        f"No climate input found for {var} "
        f"(expected {debiased.name} or {base.name})"
    )


def _resolve_backup_inputs(workdir: Path):
    precip = workdir / "precip_input_data_backup.csv"
    airtemp = workdir / "airtemp_input_data_backup.csv"
    solrad = workdir / "solrad_input_data_backup.csv"

    if all(p.exists() for p in (precip, airtemp, solrad)):
        return {
            "precip": precip,
            "airtemp": airtemp,
            "solrad": solrad,
            "sources": ("backup", "backup", "backup"),
        }

    return None


def resolve_inputs(workdir: Path):
    workdir = Path(workdir)

    if not workdir.exists():
        raise FileNotFoundError(workdir)

    grid = workdir / "input_grid.csv"
    if not grid.exists():
        raise FileNotFoundError(grid)

    precip, p_src = _resolve_climate_file(workdir, "precip")
    airtemp, t_src = _resolve_climate_file(workdir, "airtemp")
    solrad, r_src = _resolve_climate_file(workdir, "solrad")

    backup_inputs = _resolve_backup_inputs(workdir)

    return {
        "grid": grid,
        "precip": precip,
        "airtemp": airtemp,
        "solrad": solrad,
        "sources": (p_src, t_src, r_src),
        "backup": backup_inputs,
    }


# RUN PYHELP
def run_help(workdir: Path, inputs):
    helpm = HelpManager(
        str(workdir),
        path_to_grid=str(inputs["grid"]),
        path_to_precip=str(inputs["precip"]),
        path_to_airtemp=str(inputs["airtemp"]),
        path_to_solrad=str(inputs["solrad"]),
    )

    cellnames = helpm.grid.index[helpm.grid["Bassin"] == 1]

    output_help = helpm.calc_help_cells(
        path_to_hdf5=str(workdir / "help_example.out"),
        cellnames=cellnames,
        tfsoil=-1,
        sf_edepth=1,
        sf_ulai=1,
        sf_cn=1,
    )

    output_surf = helpm.calc_surf_water_cells(
        cellnames=cellnames,
        evp_surf=650,
        path_outfile=str(workdir / "surf_example.out"),
    )

    return helpm, cellnames, output_help, output_surf


# EXPORTS
def export_outputs(workdir: Path, helpm, cellnames, output, export_daily=True):
    yearly = workdir / "help_example_yearly.csv"
    output.save_to_csv(str(yearly))

    daily = None
    if export_daily:
        df = calc_area_daily_avg(cellnames, helpm.workdir)
        daily = workdir / "help_example_daily_mean.csv"
        df.to_csv(daily)

    surf = workdir / "surf_example.out"

    return yearly, daily, surf


# MAIN WRAPPER
def run_pyhelp(workdir, logger, export_daily=True):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    buf = io.StringIO()

    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            inputs = resolve_inputs(workdir)

            try:
                helpm, cellnames, output_help, output_surf = run_help(workdir, inputs)
                used_inputs = inputs["sources"]
                used_backup = 0

            except Exception as exc:
                backup = inputs.get("backup")
                if backup is None:
                    raise

                logger.warning(
                    "Primary climate inputs failed (%s). Falling back to backup inputs.",
                    exc,
                )

                backup_inputs = {
                    "grid": inputs["grid"],
                    "precip": backup["precip"],
                    "airtemp": backup["airtemp"],
                    "solrad": backup["solrad"],
                }

                helpm, cellnames, output_help, output_surf = run_help(workdir, backup_inputs)
                used_inputs = backup["sources"]
                used_backup = 1

            export_outputs(workdir, helpm, cellnames, output_help, export_daily)

        ret = 0
        diag = f"sources={used_inputs};used_backup={used_backup}"

    except Exception as exc:
        logger.exception("PyHELP failed")
        ret = 1
        diag = f"exception:{type(exc).__name__}"

    # flush stdout/stderr capturé
    for line in buf.getvalue().splitlines():
        if line.strip():
            logger.info("[pyhelp.ext] %s", line)

    logger.info("PyHELP done ret=%s diag=%s", ret, diag)

    if ret == 0:
        return ret, diag, output_help, output_surf
    return ret, diag, None, None