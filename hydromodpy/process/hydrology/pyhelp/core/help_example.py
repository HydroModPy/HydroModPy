
# -*- coding: utf-8 -*-
"""PyHELP example workflow (in-process, no env vars required).

This is kept as an example script. It uses HelpManager directly and produces:
- help_example.out (HDF5 monthly outputs)
- help_example_yearly.csv
- help_example_daily_mean.csv
"""

from __future__ import annotations

import argparse
import os.path as osp
from pathlib import Path


from .managers import HelpManager
from .daily_output import calc_area_daily_avg
from hydromodpy.core.tools import get_logger

logger = get_logger(__name__)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Run PyHELP example workflow.")
    p.add_argument("--workdir", required=True, help="Working directory containing PyHELP inputs.")
    p.add_argument("--sf-ed", type=float, default=1.0)
    p.add_argument("--sf-lai", type=float, default=1.0)
    p.add_argument("--sf-cn", type=float, default=1.0)
    p.add_argument("--tfsoil", type=float, default=-1.0)
    args = p.parse_args(argv)

    workdir = Path(args.workdir).expanduser().resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    helpm = HelpManager(
        str(workdir),
        path_to_grid=str(workdir / "input_grid_base1.csv"),
        path_to_precip=str(workdir / "precip_input_data.csv"),
        path_to_airtemp=str(workdir / "airtemp_input_data.csv"),
        path_to_solrad=str(workdir / "solrad_input_data.csv"),
    )

    # Example selection
    if "Bassin" in helpm.grid.columns:
        cellnames = helpm.grid.index[helpm.grid["Bassin"] == 1]
    else:
        cellnames = helpm.grid.index

    output_help = helpm.calc_help_cells(
        path_to_hdf5=str(workdir / "help_example.out"),
        cellnames=cellnames,
        tfsoil=args.tfsoil,
        sf_edepth=args.sf_ed,
        sf_ulai=args.sf_lai,
        sf_cn=args.sf_cn,
    )

    output_help.save_to_csv(osp.join(workdir, "help_example_yearly.csv"))

    # Daily analysis (mean over cells)
    df_daily_mean = calc_area_daily_avg(cellnames, helpm.workdir)
    df_daily_mean.to_csv(osp.join(workdir, "help_example_daily_mean.csv"))

    logger.info("Example completed in %s", workdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
