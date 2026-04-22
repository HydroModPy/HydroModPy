# -*- coding: utf-8 -*-
"""
Created on Tue Mar 24 09:45:30 2026

@author: pelissierm
"""

from pathlib import Path
import shutil

def _cleanup_dir(workdir: Path, logger, *, mode: str) -> None:

    workdir = Path(workdir)

    keep_files = {
        "input_grid.csv",
        "help_example.out",
        "help_example_yearly.csv",
        "help_example_daily_mean.csv"
    }

    delete_files = {
        "precip_input_data.csv",
        "airtemp_input_data.csv",
        "solrad_input_data.csv",
        "precip_input_data_backup.csv",
        "airtemp_input_data_backup.csv",
        "solrad_input_data_backup.csv",
    }

    if mode == "prediction":
        delete_files |= {
            "input_grid.csv",
            "precip_input_data.csv",
            "airtemp_input_data.csv",
            "solrad_input_data.csv",
        }

    removed = []

    for name in delete_files:
        p = workdir / name
        try:
            if p.exists() and p.is_file() and name not in keep_files:
                p.unlink()
                removed.append(p.name)
        except Exception as exc:
            logger.warning("[cleanup:%s] cannot delete %s: %s", mode, p, exc)

    # help_input_files reste un vrai temporaire
    temp_dir = workdir / "help_input_files"
    try:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            removed.append(temp_dir.name + "/")
    except Exception as exc:
        logger.warning("[cleanup:%s] cannot delete %s: %s", mode, temp_dir, exc)

    logger.info("[cleanup:%s] removed=%s in %s", mode, removed or "nothing", workdir)