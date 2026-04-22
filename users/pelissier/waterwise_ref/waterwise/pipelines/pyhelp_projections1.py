# -*- coding: utf-8 -*-
"""
Created on Tue Apr 14 14:04:23 2026

@author: pelissierm
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from waterwise.pipelines.pyhelp_core1 import run_pyhelp
from waterwise.predictions.prediction_preprocessing import (
    clean_pyhelp_csv,
    ensure_grid,
    filter_prediction_climate,
    prepare_projection_climate,
)


@dataclass(frozen=True)
class PredictionJob:
    ref_root: Path
    proj_root: Path
    out_root: Path
    site_core: str
    model: str


PYHELP_CLIMATE_FILES = (
    "precip_input_data.csv",
    "airtemp_input_data.csv",
    "solrad_input_data.csv",
)


def run_one_projection_job(
    job: PredictionJob,
    logger: logging.Logger,
    *,
    require_ref_daily: bool = False,
):
    ref_results = job.ref_root / f"_{job.site_core}" / "results_pyhelp"
    if not ref_results.exists():
        raise FileNotFoundError(f"Missing reference folder: {ref_results}")

    if require_ref_daily:
        ref_daily = ref_results / "help_example_daily_mean.csv"
        if not ref_daily.exists():
            raise FileNotFoundError(
                f"Reference PyHELP daily output not found for site={job.site_core}: {ref_daily}"
            )

    proj_clim_dir = job.proj_root / job.model / job.site_core
    if not proj_clim_dir.exists():
        raise FileNotFoundError(f"Missing projection climate folder: {proj_clim_dir}")

    out_model = job.out_root / job.site_core / job.model
    out_model.mkdir(parents=True, exist_ok=True)

    logger.info("Projection job: site=%s model=%s", job.site_core, job.model)

    ensure_grid(ref_results, out_model)
    prepare_projection_climate(job.site_core, ref_results, proj_clim_dir, out_model, clean_pyhelp_csv)

    for filename in PYHELP_CLIMATE_FILES:
        filter_prediction_climate(out_model / filename)

    done_file = out_model / "help_example_daily_mean.csv"
    if done_file.exists():
        logger.info("Already exists: %s (skip run)", done_file)
        return 0, "already_done"

    ret, diag = run_pyhelp(
        out_model,
        logger,
        export_daily=True,
    )

    if ret != 0:
        logger.warning(
            "PyHELP projection failed site=%s model=%s diag=%s",
            job.site_core,
            job.model,
            diag,
        )
        return ret, diag

    logger.info("[OK] done -> %s", out_model)
    return ret, diag