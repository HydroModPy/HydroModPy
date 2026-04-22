from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from waterwise.pipelines.pyhelp_core import run_pyhelp
from waterwise.pipelines.pyhelp_runtime import run_pyhelp_simulation
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


PYHELP_CLIMATE_FILES: tuple[str, ...] = (
    "precip_input_data.csv",
    "airtemp_input_data.csv",
    "solrad_input_data.csv",
)


def run_one_projection_job(
    job: PredictionJob,
    logger: logging.Logger,
    *,
    require_ref_daily: bool = False,
    keep_files: Iterable[str] | None = None,
):
    ref_results = _reference_results_dir(job)
    _validate_reference_inputs(ref_results, job, require_ref_daily=require_ref_daily)

    proj_clim_dir = _projection_climate_dir(job)
    if not proj_clim_dir.exists():
        raise FileNotFoundError(f"Missing projection climate folder: {proj_clim_dir}")

    out_model = _prepare_projection_workspace(job, ref_results, proj_clim_dir, logger)

    if _projection_already_done(out_model):
        logger.info("Already exists: %s (skip run)", out_model / "help_example_daily_mean.csv")
        ret, diag = 0, "already_done"
    else:
        ret, diag = _run_projection_simulation(job, out_model, logger)

    if ret != 0:
        logger.warning("PyHELP projection failed site=%s model=%s diag=%s", job.site_core, job.model, diag)
        return ret, diag

    logger.info("[OK] done -> %s", out_model)
    return ret, diag


def _reference_results_dir(job: PredictionJob) -> Path:
    return job.ref_root / f"_{job.site_core}" / "results_pyhelp"


def _projection_climate_dir(job: PredictionJob) -> Path:
    return job.proj_root / job.model / job.site_core


def _validate_reference_inputs(ref_results: Path, job: PredictionJob, *, require_ref_daily: bool) -> None:
    if not ref_results.exists():
        raise FileNotFoundError(f"Missing reference folder: {ref_results}")

    if require_ref_daily:
        ref_daily = ref_results / "help_example_daily_mean.csv"
        if not ref_daily.exists():
            raise FileNotFoundError(
                f"Reference PyHELP daily output not found for site={job.site_core}: {ref_daily}"
            )


def _prepare_projection_workspace(job: PredictionJob, ref_results: Path, proj_clim_dir: Path, logger: logging.Logger) -> Path:
    out_model = job.out_root / job.site_core / job.model
    out_model.mkdir(parents=True, exist_ok=True)

    logger.info("Projection job: site=%s model=%s", job.site_core, job.model)
    ensure_grid(ref_results, out_model)
    prepare_projection_climate(proj_clim_dir, out_model, clean_pyhelp_csv)
    _filter_projection_climate_inputs(out_model)
    return out_model


def _filter_projection_climate_inputs(out_model: Path) -> None:
    for filename in PYHELP_CLIMATE_FILES:
        filter_prediction_climate(out_model / filename)


def _projection_already_done(out_model: Path) -> bool:
    return (out_model / "help_example_daily_mean.csv").exists()


def _run_projection_simulation(job: PredictionJob, out_model: Path, logger: logging.Logger):
    return run_pyhelp_simulation(
        run_pyhelp,
        out_model,
        logger,
        fig_title=job.model,
        ymax=None,
        export_daily=True,
    )
