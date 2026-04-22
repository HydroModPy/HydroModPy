
from pathlib import Path

import numpy as np
import pandas as pd

from waterwise.config import (
    CerraParams,
    CerraPaths,
    ClimateWindow,
    Paths,
    RunOptions,
    RuntimeConfig,
    ensure_status_columns,
)

from waterwise.io.paths import site_paths
from waterwise.io.pyhelp_diagnostics import diag_line, diag_reset, diag_section
from waterwise.logging_utils import setup_logger
from waterwise.pipelines.pyhelp_core1 import run_pyhelp
from waterwise.pipelines.pyhelp_projections1 import PredictionJob, run_one_projection_job
from waterwise.pipelines.climate_debias_month import debias_precip_and_airtemp

from waterwise.io.stats import write_historical_stats_csv, write_prediction_stats_csv
from waterwise.io.cleaning import _cleanup_dir
from waterwise.waterwise_tools.catchment_preprocessing import convert_coordinates_inplace, run_catchment
from waterwise.waterwise_tools.base_flow1 import export_baseflow, run_streamflow_validation
import waterwise.pipelines.grid_preprocessing as pgp
import waterwise.plots.plots_climate as climate_plots
import waterwise.plots.plots_pyhelp as pyhelp_plots
from waterwise.plots.plots_projection import anomaly_maps
from waterwise.plots.parameters_plots import export_param_maps, plot_param_boxplots
from waterwise.pipelines.climate import copy_climate_from_cerra, preprocess_climate_inputs
from waterwise.pipelines.grid import GridRasters, run_grid_preprocessing
from cerra.climate_cerra import make_local_cerra, make_local_csv, make_local_mask, make_pyhelp_inputs


def build_runtime_config():
    return RuntimeConfig(
        paths=Paths(
            data_root=Path(r"Z:/HDPY_database_forModelling"),
            out_root=Path(r"C:\Users\Pelissierm\Waterwise\HDPY_models"),
            climate_root=Path(r"Z:/HDPY_database_forModelling/_climate/_cerra/_pyHelpInput"),
            base_grid_csv=Path(r"/Users/Pelissierm/Hydromodpy/users/pelissier/waterwise_0.1.0/data/input_grid_base.csv"),
        ),
        cerra_paths=CerraPaths(
            forecast_root=Path(r"Z:/_waterwise_data_process/_climate/_cerra_forecast/"),
            land_root=Path(r"Z:/_waterwise_data_process/_climate/_cerra_land/"),
            local_root=Path(r"Z:/HDPY_database_forModelling/_climate/_cerra/_local/"),
            timeserie_root=Path(r"Z:/HDPY_database_forModelling/_climate/_cerra/_timeserie/"),
            alps_grid=Path(r"Z:/_waterwise_data_process/_climate/_cerra_forecast/cerra_grid_alps.nc"),
        ),
        cerra_params=CerraParams(),
        date_window=ClimateWindow("01/01/1991", "31/12/2025", "%d/%m/%Y"),
        options=RunOptions(
            make_catchment=False,
            make_grid=False,
            make_climate_locale=False,
            make_climate_timeserie=False,
            make_climate_pyhelp=False,
            make_climate=False,
            make_climate_debiaser=False,
            run_pyhelp=True,
            run_validation=True,
            make_plots=False,
            save_png=False,
            run_predictions=False,
            stats_historical=False,
            stats_prediction=False
        ),
        rasters_dir=Path(r"Z:/HDPY_database_forModelling/pyHELP_rasters"),
        dem_path=Path(r"Z:/HDPY_database_forModelling/_dem/gedtm30_alps_epsg3035.tif"),
        sites_xlsx=Path(r"C:/Users/Pelissierm/Hydromodpy/users/pelissier/waterwise_0.1.0/data/Waterwise_sites_may2025_full_reset.xlsx"),
        xlsx_out=Path(r"C:/Users/Pelissierm/Hydromodpy/users/pelissier/waterwise_0.1.0/data/Waterwise_sites_may2025_full.xlsx"),
        ref_root=Path(r"C:\Users\Pelissierm\Waterwise\HDPY_models"),
        proj_root=Path(r"Z:\HDPY_database_forModelling\_climate\_projection\_pyHelpInput"),
        pred_out_root=Path(r"C:\Users\Pelissierm\Waterwise_predictions"),
    )


def _run_catchment_step(cfg: RuntimeConfig, df: pd.DataFrame, idx, site_id: str, logger):
    row = df.loc[idx]

    # catchment already available
    if int(float(row.get("catchment_bnd", 0))) == 1:
        return cfg.paths.out_root / site_id / "results_stable" / "geographic" / "box_buff.shp"

    # otherwise run catchment
    clip_shp = run_catchment(cfg.paths, row, str(cfg.dem_path), str(cfg.paths.out_root), sites=df, site_num=idx)

    return clip_shp


def _run_grid_step(cfg: RuntimeConfig, df: pd.DataFrame, idx, sp, clip_shp: Path, logger):
    row = df.loc[idx]

    # catchment characteristics already available
    if int(float(row.get("catchment_characteristics", 0))) == 1:
        return

    rasters = GridRasters(
        dem_250m=cfg.rasters_dir / "dem_250m.tif",
        cn=cfg.rasters_dir / "CN.tif",
        slope=cfg.rasters_dir / "Slope.tif",
        soil_depth=cfg.rasters_dir / "soil_depth.tif",
        hydroprops=cfg.rasters_dir / "Hydroprops_Alps_250m.tif",
        worldcover=cfg.rasters_dir / "Cover.tif",
        rgi_shp=cfg.rasters_dir / "rgi_clip.shp",
    )

    run_grid_preprocessing(
        pgp_module=pgp,
        in_grid=cfg.paths.base_grid_csv,
        out_grid=sp.results_pyhelp / "input_grid.csv",
        rasters=rasters,
        clip_shp=clip_shp,
        out_raster_dir=sp.clipped_rasters,
        save_png=cfg.options.save_png,
        logger=logger,
    )

    watershed_shp = cfg.paths.out_root / sp.site_id / "results_stable" / "geographic" / "watershed.shp"
    clipped_dem_path = cfg.paths.data_root / "_sites" / sp.site_id / f"{sp.site_id}_clipped_dem.tif"

    export_param_maps(
        out_dir=sp.clipped_rasters,
        clip_shp=clip_shp,
        watershed_shp=watershed_shp,
        dem_250m=rasters.dem_250m,
        hillshade_dem=clipped_dem_path,
        cn=rasters.cn,
        slope=rasters.slope,
        soil_depth=rasters.soil_depth,
        hydroprops=rasters.hydroprops,
        worldcover=rasters.worldcover,
    )

    plot_param_boxplots(
        csv_path=str(sp.results_pyhelp / "input_grid.csv"),
        save_dir=str(sp.results_pyhelp / "boxplots_params")
    )



def _run_climate_steps(cfg: RuntimeConfig, df: pd.DataFrame, idx, sp, logger):
    row = df.loc[idx]

    # local climate already available in CSV skip whole historical climate block
    if int(float(row.get("local_climate", 0))) == 1:
        return

    if cfg.options.make_climate_locale :
        site_mask = make_local_mask(
            workdir=sp.site_root,
            alps_grid_file=cfg.cerra_paths.alps_grid,
            buffer=cfg.cerra_params.local_buffer,
            reset=True,
            site_epsg=cfg.cerra_params.site_shape_epsg,
            checkplot=False,
            verbose=False,
            logger=logger,
        )
        if isinstance(site_mask, np.ndarray):
            make_local_cerra(
                mask=site_mask,
                site_id=sp.site_id,
                local_dir=cfg.cerra_paths.local_root,
                alps_forecast_dir=cfg.cerra_paths.forecast_root,
                alps_land_dir=cfg.cerra_paths.land_root,
                years=cfg.cerra_params.date_window,
                logger=logger,
                reset=True,
                variables={
                    "2m_temperature": "forecast",
                    "surface_solar_radiation_downwards": "forecast",
                    "total_precipitation": "land",
                },
            )

    if cfg.options.make_climate_timeserie:
        make_local_csv(
            site_id=sp.site_id,
            local_dir=cfg.cerra_paths.local_root,
            variables=["surface_solar_radiation_downwards", "total_precipitation", "2m_temperature"],
            logger=logger,
            checkplot=True,
            timeserie_dir=cfg.cerra_paths.timeserie_root,
        )

    if cfg.options.make_climate_pyhelp :
        make_pyhelp_inputs(
            site_id=sp.site_id,
            grid_file=sp.results_pyhelp / "input_grid.csv",
            local_dir=cfg.cerra_paths.local_root,
            pyhelp_dir=cfg.paths.climate_root,
            params=cfg.cerra_params,
            logger=logger,
            variables=["surface_solar_radiation_downwards", "total_precipitation", "2m_temperature"],
            verbose=False,
            checkplot=True,
            newGrid=False,
        )

    if cfg.options.make_climate :
        climate_map = copy_climate_from_cerra(sp.site_id, cfg.paths.climate_root, sp.results_pyhelp, logger)
        preprocess_climate_inputs(
            climate_map,
            sp.results_pyhelp,
            decimals=2,
            date_window=cfg.date_window,
            logger=logger
        )
        
    if cfg.options.make_climate_debiaser:
        debias_precip_and_airtemp(sp.site_id, sp.results_pyhelp)


def _run_pyhelp_step(cfg: RuntimeConfig, df: pd.DataFrame, idx, sp, logger):
    row = df.loc[idx]
    if int(float(row.get("Pyhelp_hist", 0))) == 1:
        diag_line(cfg.paths.out_root, f"{sp.site_id}.pyhelp", "skipped_existing")
        return 0, None, None

    ret, diag, output_help, output_surf = run_pyhelp(sp.results_pyhelp, logger, export_daily=True)
    diag_line(cfg.paths.out_root, f"{sp.site_id}.pyhelp", diag)
    return ret, output_help, output_surf
        

def _run_validation_step(cfg, df, idx, sp, site_id, logger, output_help, output_surf):
    row = df.loc[idx]
    if int(float(row.get("Pyhelp_hist", 0))) == 1:
        return
    
    try:
        ret, diag = export_baseflow(site_id, workdir=sp.results_pyhelp, logger=logger)
        diag_line(cfg.paths.out_root, f"{site_id}.baseflow", diag)

        if ret != 0:
            return ret

        if output_help is None or output_surf is None:
            logger.warning("Skip streamflow validation for %s: missing PyHELP outputs", site_id)
            diag_line(cfg.paths.out_root, f"{site_id}.streamflow_validation", "missing_pyhelp_outputs")
            return 0

        ret, diag = run_streamflow_validation(site_id, workdir=sp.results_pyhelp, output_help=output_help,
            output_surf=output_surf, logger=logger)
        diag_line(cfg.paths.out_root, f"{site_id}.streamflow_validation", diag)

        return ret

    except Exception:
        logger.exception("Observed baseflow / validation step failed for %s", site_id)
        diag_line(cfg.paths.out_root, f"{site_id}.baseflow", "exception")
        diag_line(cfg.paths.out_root, f"{site_id}.streamflow_validation", "exception")
        return 1

def _run_historical_plots_step(cfg: RuntimeConfig, df: pd.DataFrame, idx, sp, logger):
    row = df.loc[idx]

    if int(float(row.get("Pyhelp_plots", 0))) == 1:
        return
    
    climate_plots.plot_climate_boxplots(
        workdir=str(sp.results_pyhelp),
        save_dir=str(sp.results_pyhelp / "boxplots_climate")
    )   

    climate_plots.plot_climate_mean_maps(
        workdir=sp.results_pyhelp,
        watershed_shp=sp.site_root / "results_stable" / "geographic" / "watershed.shp",
        save_dir=sp.results_pyhelp / "climatic_plots"     
    )
    
    climate_plots.plot_climate_timeseries_batch(
        workdir=sp.results_pyhelp,
        save_dir=sp.results_pyhelp/"climatic_plots"
    )
    
    pyhelp_plots.generate_historical_pyhelp_plots(
        workdir=sp.results_pyhelp,
        save_dir=sp.results_pyhelp / "plots_pyhelp",
        watershed_shp=sp.site_root / "results_stable" / "geographic" / "watershed.shp",
        glaciers_shp=cfg.rasters_dir / "rgi_clip.shp",
        hillshade_dem=cfg.dem_path,
    )
    
    pyhelp_plots.generate_builtin_pyhelp_plots(
        workdir=str(sp.results_pyhelp),
        save_dir=str(sp.results_pyhelp / "plots_pyhelp")
    )


def _run_historical_stats_step(cfg: RuntimeConfig, df: pd.DataFrame, idx, sp, logger):
    row = df.loc[idx]

    if int(float(row.get("Pyhelp_stats", 0))) == 1:
        return

    write_historical_stats_csv(
        workdir=sp.results_pyhelp,
        logger=logger,
    )
    
    # _cleanup_dir(
    #     sp.results_pyhelp,
    #     logger,
    #     mode="historical",
    # )


def _run_prediction_steps(cfg: RuntimeConfig, df: pd.DataFrame, idx, site_id: str, logger):
    row = df.loc[idx]

    if int(float(row.get("Pyhelp_prediction", 0))) == 1:
        return

    target_models = ["_CESM2", "_inm_cm5_0", "_gfdl_esm4"]
    site_core = site_id.lstrip("_")

    for model in target_models:
        job = PredictionJob(
            ref_root=cfg.ref_root,
            proj_root=cfg.proj_root,
            out_root=cfg.pred_out_root,
            site_core=site_core,
            model=model,
        )
        run_one_projection_job(job, logger=logger, require_ref_daily=False)        
        

def _run_prediction_plots_step(cfg: RuntimeConfig, df: pd.DataFrame, idx, sp, site_id: str, logger):
    row = df.loc[idx]

    if int(float(row.get("Pyhelp_plots", 0))) == 1:
        return

    site_core = site_id.lstrip("_")
    basin_shp = cfg.paths.out_root / f"_{site_core}" / "results_stable" / "geographic" / "watershed.shp"

    for model in ["_CESM2", "_inm_cm5_0", "_gfdl_esm4"]:
        model_dir = cfg.pred_out_root / site_core / model

        out_file = model_dir / "help_example.out"
        if not out_file.exists():
            logger.warning("Prediction output missing, skip plots: %s", out_file)
            continue

        pyhelp_plot_dir = model_dir / "plots_pyhelp"
        pyhelp_plot_dir.mkdir(parents=True, exist_ok=True)

        anomaly_maps(
            out_file=out_file,
            outdir=pyhelp_plot_dir,
            basin_shp=basin_shp,
            scenario_name=model,
        )
        

def _run_prediction_stats_step(cfg: RuntimeConfig, df: pd.DataFrame, idx, sp, logger):
    row = df.loc[idx]

    if int(float(row.get("Pyhelp_stats", 0))) == 1:
        return

    target_models = ["_CESM2", "_inm_cm5_0", "_gfdl_esm4"]

    for model in target_models:
        model_dir = cfg.pred_out_root / "peca" / model

        write_prediction_stats_csv(
            model_dir=model_dir,
            logger=logger,
        )
        
        # _cleanup_dir(
        #     model_dir,
        #     logger,
        #     mode="prediction",
        # )


def run_site_pipeline(cfg: RuntimeConfig, df: pd.DataFrame, idx, logger):
    site_id = str(df.at[idx, "ID_name"])
    sp = site_paths(cfg.paths.out_root, site_id)
    sp.results_pyhelp.mkdir(parents=True, exist_ok=True)
    sp.clipped_rasters.mkdir(parents=True, exist_ok=True)

    diag_section(cfg.paths.out_root, site_id)
    diag_line(
        cfg.paths.out_root,
        "shp.create",
        int(str(df.at[idx, "shp_upload"]) == "1") if "shp_upload" in df.columns else 0,
    )

    clip_shp = cfg.paths.out_root / site_id / "results_stable" / "geographic" / "box_buff.shp"

    if cfg.options.make_catchment:
        clip_shp = _run_catchment_step(cfg, df, idx, site_id, logger)

    if cfg.options.make_grid:
        _run_grid_step(cfg, df, idx, sp, clip_shp, logger)

    if any([
        cfg.options.make_climate_locale,
        cfg.options.make_climate_timeserie,
        cfg.options.make_climate_pyhelp,
        cfg.options.make_climate,
    ]):
        _run_climate_steps(cfg, df, idx, sp, logger)

    if cfg.options.run_pyhelp:
        ret, output_help, output_surf = _run_pyhelp_step(cfg, df, idx, sp, logger)
        if cfg.options.run_validation and ret == 0:
            _run_validation_step(cfg, df, idx, sp, site_id, logger, output_help, output_surf)
        
    if cfg.options.make_plots:
        _run_historical_plots_step(cfg, df, idx, sp, logger)
    
    if cfg.options.stats_historical:
        _run_historical_stats_step(cfg, df, idx, sp, logger)

    if cfg.options.run_predictions:
        _run_prediction_steps(cfg, df, idx, site_id, logger)
        
    if cfg.options.make_plots:
        _run_prediction_plots_step(cfg, df, idx, sp, site_id, logger)

    if cfg.options.stats_prediction:
        _run_prediction_stats_step(cfg, df, idx, sp, logger)
        

def main():
    cfg = build_runtime_config()
    cfg.paths.out_root.mkdir(parents=True, exist_ok=True)
    logger = setup_logger("waterwise", log_file=cfg.paths.out_root / "run_waterwise.log")

    df = pd.read_excel(cfg.sites_xlsx)
    convert_coordinates_inplace(df)
    ensure_status_columns(df)
    diag_reset(cfg.paths.out_root)

    for idx in df.index:
        run_site_pipeline(cfg, df, idx, logger)

    if cfg.xlsx_out is not None:
        df.to_excel(cfg.xlsx_out, index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
