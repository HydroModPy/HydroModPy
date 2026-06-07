from __future__ import annotations

import datetime
import logging
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from src import watershed_root
from src.display import visualization_watershed
from src.tools import toolbox

from .config import ProjectConfig

if not hasattr(np, "ComplexWarning"):
    np.ComplexWarning = Warning

try:
    import deepdish as dd
except Exception:
    dd = None


@dataclass
class DamInputs:
    dataframe: pd.DataFrame
    level_init: float
    resti_short: pd.Series


@dataclass
class ModelOutputs:
    model_name: str
    success_modflow: bool
    model_modflow: object
    timeseries_results: Optional[object]
    netcdf_results: Optional[object]
    timeseries_dataframe: Optional[pd.DataFrame]


def _build_watershed_name(config: ProjectConfig) -> str:
    today = pd.to_datetime("today").strftime("%Y-%m-%d")
    if config.general.watershed_name_style == "simplex":
        return "_".join([config.general.watershed_prefix, today, config.general.simplex_tag])

    timestamp = datetime.datetime.now().strftime("%H-%M")
    return "_".join(
        [
            config.general.watershed_prefix,
            today,
            timestamp,
            config.general.freq_input,
        ]
    )


def initialize_watershed(config: ProjectConfig, data_path: str, out_path: str):
    dem_path = config.paths.dem_path(data_path)
    if not os.path.exists(dem_path):
        raise FileNotFoundError(f"DEM introuvable: {dem_path}")

    watershed_name = _build_watershed_name(config)
    logging.info("##### %s #####", watershed_name.upper())

    BV = watershed_root.Watershed(
        dem_path=dem_path,
        out_path=out_path,
        load=config.general.load_geographic,
        watershed_name=watershed_name,
        from_xyv=list(config.general.from_xyv),
        save_object=config.general.save_object,
    )

    if config.general.subbassin:
        hydrometry_path = os.path.join(data_path, "Stations jaugeage")
        BV.add_hydrometry(hydrometry_path, "france hydrometric stations.shp")

        intermittency_path = os.path.join(data_path, "Stations ONDE")
        BV.add_intermittency(intermittency_path, "regional onde stations.shp")
        BV.add_subbasin(sub_snap_dist=200)

    geol_path = os.path.join(data_path, "Geologie")
    BV.add_geology(geol_path, types_obs="GEO1M.shp", fields_obs="CODE_LEG")

    hydro_path = os.path.join(data_path, "Hydrographie")
    BV.add_hydrography(hydro_path, types_obs=["CoursEau_FXX_clip_bre"], fields_obs=["fid"])

    if config.general.visual_plot:
        visualization_watershed.watershed_local(dem_path, BV)
        visualization_watershed.watershed_geology(BV)
        visualization_watershed.watershed_dem(BV)

    BV.add_climatic()
    return BV


def load_climate_to_watershed(BV, config: ProjectConfig, data_path: str) -> pd.DataFrame:
    climate_path = config.paths.climate_path(data_path)
    logging.info("Chargement des données climatiques: %s", climate_path)

    df = pd.read_csv(climate_path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index)
    df = df.loc[
        (df.index >= pd.Timestamp(f"01/01/{config.general.first_year}"))
        & (df.index <= pd.Timestamp(f"31/12/{config.general.last_year}"))
    ]
    df = df.resample(config.general.freq_input).agg(config.climate_agg_rules)

    BV.climatic.recharge = df["recharge"]
    BV.climatic.runoff = df["runoff"]
    BV.climatic.precip = df["precip"]
    BV.climatic.evt = df["evt"]
    BV.climatic.etp = df["etp"]
    BV.climatic.t = df["t"]

    BV.climatic.update_first_clim(BV.climatic.recharge.iloc[0])
    return df


def _build_resti_short(dam_df: pd.DataFrame, threshold: float) -> pd.Series:
    resti1 = dam_df.iloc[0]["resti"]
    date_idx = []

    for current_date in dam_df.index[:-1]:
        resti2 = dam_df.loc[current_date, "resti"]
        if resti2 != 0 and abs(resti1 - resti2) / resti2 > threshold:
            date_idx.append(current_date)
        resti1 = resti2

    date_idx = [dam_df.index[0]] + date_idx + [dam_df.index[-1]]
    resti_short = pd.Series(index=date_idx, name="resti", dtype=float)

    for i in range(0, resti_short.size - 1):
        id1 = resti_short.index[i]
        id2 = resti_short.index[i + 1]
        window = dam_df[id1:id2][0:-1]["resti"]
        resti_short.loc[id1] = window.mean()

    return resti_short[0:-1]


def load_dam_inputs(
    BV,
    config: ProjectConfig,
    data_path: str,
    climate_index: pd.DatetimeIndex,
) -> DamInputs:
    dam_path = config.paths.dam_input_path(data_path)
    logging.info("Chargement des données barrage: %s", dam_path)

    dam_df = pd.read_csv(
        dam_path,
        sep=";",
        header=0,
        skiprows=0,
        index_col="time",
        parse_dates=True,
        dayfirst=True,
    )

    dam_df = dam_df.resample(config.general.freq_input).agg(config.dam_agg_rules)
    dam_df = dam_df.loc[
        (dam_df.index >= pd.Timestamp(f"01/01/{config.general.first_year}"))
        & (dam_df.index <= pd.Timestamp(f"31/12/{config.general.last_year}"))
    ]

    first_date = climate_index[0]
    if first_date in dam_df.index:
        level_init = dam_df.loc[first_date, "cheze_lvl"]
    else:
        nearest = dam_df.index[abs(dam_df.index - first_date).argmin()]
        level_init = dam_df.loc[nearest, "cheze_lvl"]
        logging.warning(
            "Date %s absente des données barrage, valeur la plus proche utilisée: %s",
            first_date,
            nearest,
        )

    if hasattr(level_init, "item"):
        level_init = level_init.item()

    dam_df.iloc[0] = toolbox.hydrological_mean(dam_df, 4)
    resti_short = _build_resti_short(dam_df, config.reservoir.resti_threshold)

    return DamInputs(dataframe=dam_df, level_init=level_init, resti_short=resti_short)


def configure_reservoir(
    BV,
    config: ProjectConfig,
    data_path: str,
    climate_df: pd.DataFrame,
    dam_inputs: DamInputs,
) -> None:
    BV.add_lakeres()

    lake_id = config.reservoir.lake_id
    BV.lakeres.new_lakeres(config.reservoir.mask_path(data_path), lake_id)
    BV.lakeres.update_stagemax(lake_id, config.reservoir.stagemax)
    BV.lakeres.update_lakebed_leakance(lake_id, config.reservoir.leakance_m_day)
    BV.lakeres.update_bathymetry(lake_id, config.reservoir.bathymetry_path(data_path))

    outlet_path = config.reservoir.outlet_path(data_path)
    if outlet_path:
        BV.lakeres.update_outlet(lake_id, outlet_path)

    BV.lakeres.update_stageinit(lake_id, dam_inputs.level_init)

    BV.lakeres.update_precip(lake_id, climate_df["precip"])
    BV.lakeres.update_evap(lake_id, climate_df["evt"])
    BV.lakeres.update_runoff(
        lake_id,
        climate_df["runoff"] * (BV.geographic.resolution**2),
        runoff_accumulation=True,
    )

    dam_df = dam_inputs.dataframe
    withdraw_fill_ts = dam_df["usine"] - dam_df["canut"] - dam_df["meu"]
    withdraw_fill_ts = withdraw_fill_ts + dam_df["resti"]
    BV.lakeres.update_withdraw_fill(lake_id, withdraw_fill_ts)

    BV.lakeres.connect_returnflow(lake_id, dam_inputs.resti_short)

    if config.general.save_object:
        BV.save_object()


def configure_streamflow(BV, config: ProjectConfig) -> None:
    if not config.streamflow.enabled:
        return

    BV.add_streamflow_seepage(icalc=config.streamflow.icalc)
    BV.streamflow_seepage.update_area("watershed", config.streamflow.area_fraction)

    BV.streamflow_seepage.update_segment_data("thickm", config.streamflow.thickm)
    BV.streamflow_seepage.update_segment_data("depth", config.streamflow.depth)
    BV.streamflow_seepage.update_segment_data("hcond", config.streamflow.hcond_max)
    BV.streamflow_seepage.update_segment_data("roughch", config.streamflow.roughch)

    BV.streamflow_seepage.correct("multiple_reaches", config.streamflow.correct_multiple_reaches)
    BV.streamflow_seepage.correct("elevations", config.streamflow.correct_elevations)

    if config.general.save_object:
        BV.save_object()


def configure_model_settings(BV, config: ProjectConfig) -> None:
    BV.add_settings()
    BV.settings.update_model_name(config.general.model_name)

    BV.add_hydraulic()

    BV.settings.update_box_model(config.general.box)
    BV.settings.update_sink_fill(config.general.sink_fill)
    BV.settings.update_simulation_state(config.general.sim_state)
    BV.settings.update_check_model(plot_cross=config.general.plot_cross)

    hydro = config.hydraulic
    BV.hydraulic.update_nlay(hydro.nlay)
    BV.hydraulic.update_lay_decay(hydro.lay_decay)
    BV.hydraulic.update_bottom(hydro.bottom)
    BV.hydraulic.update_thick(hydro.thick)
    BV.hydraulic.update_hk(hydro.hk_m_day)
    BV.hydraulic.update_sy(hydro.sy)
    BV.hydraulic.update_hk_vertical(hydro.hk_vertical)
    BV.hydraulic.update_cond_drain(hydro.cond_drain)
    BV.hydraulic.update_lay_decay(hydro.poro_decay)

    BV.settings.update_bc_sides(config.boundary.bc_left, config.boundary.bc_right)
    BV.add_oceanic(config.boundary.sea_level)
    BV.settings.update_dis_perlen(config.general.dis_perlen)

    if config.general.save_object:
        BV.save_object()


def run_modflow_and_postprocess(BV, config: ProjectConfig) -> ModelOutputs:
    model_name = BV.settings.model_name
    model_modflow = BV.preprocessing_modflow()

    if config.general.save_object:
        BV.save_object()

    success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)

    if dd is not None:
        h5file = os.path.join(BV.simulations_folder, f"results_listing_{model_name}")
        dd.io.save(
            h5file,
            {
                "model_name": model_name,
                "success_modflow": success_modflow,
                "model_modflow": model_modflow,
            },
        )
    else:
        logging.warning("deepdish indisponible: results_listing non sauvegardé.")

    timeseries_results = None
    timeseries_df = None
    netcdf_results = None

    if success_modflow:
        BV.postprocessing_modflow(
            model_modflow,
            watertable_elevation=True,
            watertable_depth=True,
            seepage_areas=True,
            outflow_drain=True,
            groundwater_flux=True,
            groundwater_storage=True,
            accumulation_flux=True,
            lake_leakage=True,
            export_all_tif=False,
        )

        model_modpath = None
        timeseries_results = BV.postprocessing_timeseries(
            model_modflow,
            model_modpath,
            datetime_format=True,
            subbasin_results=True,
        )
        if timeseries_results is not None and hasattr(timeseries_results, "mfdata"):
            timeseries_df = timeseries_results.mfdata

        netcdf_results = BV.postprocessing_netcdf(model_modflow, datetime_format=True)

    return ModelOutputs(
        model_name=model_name,
        success_modflow=success_modflow,
        model_modflow=model_modflow,
        timeseries_results=timeseries_results,
        netcdf_results=netcdf_results,
        timeseries_dataframe=timeseries_df,
    )
