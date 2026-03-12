# -*- coding: utf-8 -*-
"""
Created on Fri Mar 21 10:39:38 2025

@author: Ronan
"""

#%% ---- LIBRAIRIES

# Libraries installed by default
import sys
import os
import tomllib
from pathlib import Path

from flopy import run_model
import numpy as np
import pandas as pd
import geopandas as gpd
import glob
import pickle
import matplotlib.dates as mdates
import rasterio
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
from itertools import islice
from mpl_toolkits.axes_grid1 import make_axes_locatable
import xarray as xr
import rioxarray as rxr
import pickle

import imageio.v2 as imageio
import whitebox

# Add
import flopy.utils.binaryfile as bf
from PIL import Image

# ROOT DIRECTORY
from os.path import dirname, abspath
# try:
root_dir = dirname(dirname(dirname(abspath(__file__))))
# except NameError:
#     root_dir = os.getcwd()
sys.path.append(root_dir)

# HYDROMODPY MODULES
import hydromodpy as hmp
from hydromodpy.geographic import Geographic, Subbasin
from hydromodpy.data_managers.climatic import Climatic
from hydromodpy.watershed_legacy import Driasclimat, Driaseau, \
    Hydrography, Intermittency, Settings, \
    SafranSurfex
from hydromodpy.data_managers.hydrometry.config import HydrometryConfig
from hydromodpy.data_managers.hydrometry.manager import HydrometryManager
from hydromodpy.data_managers.oceanic import Oceanic
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.display import visualization_watershed, visualization_results, export_vtuvtk
from hydromodpy.tools import toolbox
from hydromodpy.domain import (
    Domain,
)
from hydromodpy.data_managers.geology.geology_field import GeologyField
from hydromodpy.process import Flow, Transport
from hydromodpy.process.flow.sinks_sources import FlowRechargeConfig
from hydromodpy.solver.modflow_nwt import (
    Modflow,
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
    Modpath,
    Mt3dms,
)
from hydromodpy.solver.modflow6 import Modflow6, Modflow6Transport
from hydromodpy.solver import SolverEngine
from hydromodpy.postprocess import netcdf
from hydromodpy.postprocess import timeseries
from hydromodpy.postprocess.flow.matching_streams import MatchingStreams
from hydromodpy.pyhelp import preprocessing_pyhelp, PyhelpGridParams
fontprop = toolbox.plot_params(8,15,18,20)  # small, medium, interm, large

config_path = Path(__file__).parent / "config.toml"
cfg = HydroModPyConfig.from_toml(config_path)
out_path = cfg.workspace.out_dir_path
solver_engine = cfg.solver.solver_engine

with config_path.open('rb') as f:
    raw_toml = tomllib.load(f)

#%% ---- EXTRACT CATCHMENT

if __name__ == '__main__':

    # Test overrides via env vars
    if os.environ.get("HYDROMODPY_OUT_PATH"):
        out_path = Path(os.environ["HYDROMODPY_OUT_PATH"])
    display_plots = os.environ.get("HYDROMODPY_NO_DISPLAY") != "1"
    display_3D = display_plots

    wbt = whitebox.WhiteboxTools()
    wbt.verbose = False

    cfg.workspace.out_dir_path = out_path
    watershed_name = cfg.workspace.catch_name
    print('##### '+watershed_name.upper()+' #####')

    data_path = cfg.workspace.data_path

    workspace = hmp.Workspace(config=cfg.workspace)

    # ------------------------------------------------------------------ #
    # EXEMPLE : instancier GeographicConfig directement en Python,
    # sans passer par le fichier TOML.  Décommenter le bloc ci-dessous
    # et commenter la ligne  ``geographic = hmp.Geographic(cfg.geographic, workspace)``
    # pour l'utiliser.
    #
    # from hydromodpy.geographic.geographic_config import GeographicConfig
    #
    # geo_cfg = GeographicConfig(
    #     catch_def      = "from_outlet_coord",
    #     dem_init_path  = Path("../../data/Brittany/dem/regional dem.tif"),
    #     cell_size      = 100.0,
    #     x_outlet       = 265611.933,
    #     y_outlet       = 6784182.776,
    #     snap_dist      = 50,
    #     buff_area      = 20.0,
    #     polyg_shp_path = Path("../../data/Brittany/shape/watershed.shp"),
    #     crs_project    = "EPSG:2154",
    #     dem_correc_type = "breach",
    #     bottom_path    = Path("../../data/Brittany/dem/regional_dem_full.tif"),
    #     reg_fold       = Path("../../data/Brittany/dem/correcflow"),
    # )
    # geographic = hmp.Geographic(geo_cfg, workspace)
    # ------------------------------------------------------------------ #

    geographic = hmp.Geographic(cfg.geographic, workspace)
    surface_topo = geographic.get_domain_surface_topo()
    domain = Domain(
        config=cfg.domain,
        surface_topo=surface_topo,
    )
    if "geology" in cfg.data.types:
        geology = GeologyField.from_watershed_config(
            cfg.data.geology,
            raster_support=surface_topo.support,
        )
        domain.set_zone("geology", geology)

    flow = Flow(config=cfg.flow)

    setting = Settings()

    transport = Transport(config=cfg.transport)

    #%% DATA

    area = int(round(geographic.catch_area))

    hydrography = Hydrography(out_path=workspace.catch_folder,
                                                   types_obs=['botopage2024_naizin_streams_perennial-intermittent'],
                                                   fields_obs=['FID'],
                                                   geographic=geographic,
                                                   hydro_path=data_path,
                                                   streams_file=None)

    subbasin = Subbasin(geographic=geographic,
                        hydrometry=None,
                        intermittency=None,
                        add_path=data_path,
                        out_path=workspace.catch_folder,
                        sub_snap_dist=50)

    # hydrometry = Hydrometry(out_path=workspace.catch_folder,
    #                         hydrometry_path=data_path,
    #                         file_name='france hydrometric stations.shp',
    #                         geographic=geographic)

    # Load hydrometry from TOML [hydrometry] section
    hydro_section = raw_toml.get("hydrometry", {})
    hydrometry = None
    if hydro_section:
        try:
            from datetime import datetime as dt
            hydro_cfg = HydrometryConfig.model_validate(hydro_section)
            period = None
            if hydro_cfg.date_start and hydro_cfg.date_end:
                period = (dt.fromisoformat(hydro_cfg.date_start), dt.fromisoformat(hydro_cfg.date_end))
            for src in hydro_cfg.sources:
                if not src.mask_path:
                    src.mask_path = Path(geographic.watershed_shp)
            manager = HydrometryManager(
                config=hydro_cfg,
                project_period=period,
                project_extent=None,
            )
            hydrometry = manager.load()
        except Exception as e:
            print(f"Warning: Hydrometry loading failed - {e}")
            print("Continuing without hydrometric stations...")
            hydrometry = None

    intermittency = Intermittency(out_path=workspace.catch_folder,
                                  intermittency_path=data_path,
                                  file_name='regional onde stations.shp',
                                  geographic=geographic)

    #%% CLIMATIC

    climatic = Climatic(out_path=workspace.catch_folder)

    #%% OCEANIC

    oceanic = Oceanic()
    oceanic.extract_local_data(out_path=workspace.catch_folder,
                                 geographic=geographic,
                                 oceanic_path=data_path)
    try:
        oceanic.download_SHOM_data(geographic=geographic,
                                    start_date='2003-01-01',
                                    end_date='2003-01-30')
        oceanic.update_MSL(oceanic.SHOM_data['value'].mean())
    except Exception as _shom_exc:
        print(f"SHOM download failed ({_shom_exc}), using default MSL=0.0")
        oceanic.update_MSL(0.0)

    flow.boundary_conditions["ocean"].value = oceanic.MSL

    #%% WATERSHED OBJECT

    stable_folder      = cfg.workspace.stable_folder
    simulations_folder = cfg.workspace.simulations_folder
    calibration_folder = workspace.calibration_folder # necessary for plots

    #%% VISUALIZATION

    visualization_watershed.watershed_local(cfg.geographic.dem_init_path, workspace, geographic)
    visualization_watershed.watershed_dem(
        workspace,
        geographic,
        hydrography=hydrography,
        piezometry=None,
        intermittency=intermittency,
        hydrometry=hydrometry,
    )

    # Add hydrological data

    #%% ---- ATMOSPHERE



        #%% INIT

        # ATMOSPHERE : Necessary to set model parameters

    # climatic.update_sim2_reanalysis(var_list=['t', 'precip', 'dli'],
    #                                        nc_data_path=Path(workspace.catch_folder) / 'results_stable' / 'climatic',
    #                                        first_year=2003,
    #                                        last_year=2003,
    #                                        time_step='ME',
    #                                        sim_state='transient',
    #                                        spatial_mean=True,
    #                                        geographic=geographic,
    #                                        disk_clip=geographic.watershed_shp) # for clipping the netcdf files saved on disk
    #                                                                 # can be a shapefile path or a flag: 'watershed' or False

    #%% ---- PYHELP
    pyhelp_activated = True
    if pyhelp_activated == True:

        pyhelp_workdir = Path(cfg.workspace.out_dir_path) / watershed_name / "results_pyhelp"
        pyhelp_workdir.mkdir(parents=True, exist_ok=True)

        dem_path_modflow = geographic.watershed_box_buff_dem

        #DEM generated by hydromodpy (result stable) is resampled during pyhelp preprocessing
        #to 250m for computation efficiency
        dem_path_pyhelp = Path(cfg.workspace.stable_folder, "geographic", "watershed_box_buff_dem.tif")

        #optional, for catchment size clipping
        shapefile_path = geographic.watershed_shp

        pyhelp_workdir = Path(out_path, watershed_name, "results_pyhelp")

        #If already completed input grid:
        grid_ready = Path(data_path, "pyhelp_input_grid_ready.csv")

        #%% CLIMATIC CSVS

        #reanalysis netcdf files for adequatly formated pyhelp climatic input CSVs transformation
        nc_folder = [
            Path(cfg.workspace.stable_folder, "climatic", "PRETOT_SIM2_20000101_20091231.nc"),
            Path(cfg.workspace.stable_folder, "climatic", "T_SIM2_20000101_20091231.nc"),
            Path(cfg.workspace.stable_folder, "climatic", "DLI_SIM2_20000101_20091231.nc")
            ]

        #already available correctly formated pyhelp climatic input CSVs
        ready_climatic_csvs = [
            Path(data_path, "pyhelp_precip_input_data.csv"),
            Path(data_path, "pyhelp_airtemp_input_data.csv"),
            Path(data_path, "pyhelp_solrad_input_data.csv")
            ]

        #%% RUN

        #Updateable input grid parameters.
        #Spatially Homogeneous grid (same parameter applied to every pixel of grid)
        params = PyhelpGridParams(
            growth_start=120,
            growth_end=266,
            wind=10,
            hum1=60, hum2=65, hum3=70, hum4=70,
            LAI=4,
            EZD=57,
            CN=50,
            nlayer=1,
            lay_type1=1,
            thick1=100,
            poro1=0.45,
            fc1=0.23,
            wp1=0.116,
            ksat1=0.1,
            dist_dr1=50,
            slope1=8
                )

        sim_name = "_sim_"
        sim_dir = Path(pyhelp_workdir, sim_name)
        sim_dir.mkdir(parents=True, exist_ok=True)

        nc = preprocessing_pyhelp(
            workdir=str(sim_dir),
            pyhelp_out_nc=str(sim_dir / "pyhelp_daily_out.nc"),
            #grid_ready=str(grid_ready),
            grid_base=str(data_path / "input_grid_base.csv"),
            dem=str(dem_path_pyhelp),
            shapefile=shapefile_path,
            grid_params=params,
            compress_level=4,
            #nc_folder=nc_folder
            ready_climatic_csvs = ready_climatic_csvs
        )
        print("NetCDF :", nc)


        #%% SCALING
        #Modflow recharge input generation from pyhelp outputs

        nc_path = Path(pyhelp_workdir, sim_name, "pyhelp_daily_out.nc")
        dem_path = Path(stable_folder, "geographic", "watershed_box_buff_dem.tif")

        ds = xr.open_dataset(nc_path)
        dem = rxr.open_rasterio(dem_path)

        R = ds["rechg"]
        R = R.rio.write_crs(dem.rio.crs)

        Rt = R.rio.reproject_match(dem, nodata=0.0)
        cube = Rt.values / 1000

        recharge_dict = {i: cube[i] for i in range(cube.shape[0])}


    #%% ---- RECHARGE

    #%% DATA SAFRAN-ISBA

    climatic.update_recharge_reanalysis(path_file=data_path / '_climate_REANALYSIS.csv',
                                        clim_mod='REA',
                                        clim_sce='historic',
                                        first_year=2003,
                                        last_year=2003,
                                        time_step='ME',
                                        sim_state='transient')

    climatic.update_runoff_reanalysis(path_file=data_path / '_climate_REANALYSIS.csv',
                                        clim_mod='REA',
                                        clim_sce='historic',
                                        first_year=2003,
                                        last_year=2003,
                                        time_step='ME',
                                        sim_state='transient')

    def select_period(df, first, last):
        df = df[(df.index.year>=first) & (df.index.year<=last)]
        return df

    R_mm_day = climatic.recharge
    r_mm_day = climatic.runoff

    #%% SYNTHETIC RECHARGE

    R_mm_day_filt = select_period(R_mm_day, 2003, 2003)*0
    R_mm_day_filt[R_mm_day_filt.index.month.isin([3,4,5,6,8,9,10])] = 0
    R_mm_day_filt[R_mm_day_filt.index.month.isin([1,2,11,12])] = 2
    R_mm_day_filt[R_mm_day_filt.index.month.isin([7])] = -1
    # plt.plot(R_mm_day_filt)

    R_mm_day_filt.index = pd.to_datetime(R_mm_day_filt.index)

    if display_plots:
        fig, axs = plt.subplots(3,1, figsize=(8,8), sharex=True)
        axs = axs.ravel()

        ax = axs[0]
        ax.plot(30*R_mm_day, label='Recharge', c='navy', lw=1)
        ax.fill_between(R_mm_day.index, 30*R_mm_day, (30*R_mm_day)+(30*r_mm_day), label='Recharge + Runoff', color='dodgerblue', lw=0.5, alpha=1)
        ax.set_ylabel('R [mm/month]')
        ax.legend(loc='upper right')
        ax.set_title('No log', fontsize=8)

        ax = axs[1]
        ax.plot(30*R_mm_day, label='Recharge', c='navy', lw=1)
        ax.fill_between(R_mm_day.index, 30*R_mm_day, (30*R_mm_day)+(30*r_mm_day), label='Recharge + Runoff', color='dodgerblue', lw=0.5, alpha=1)
        ax.set_yscale('log')
        ax.set_title('Log', fontsize=8)
        ax.set_ylabel('R [mm/month]')

        ax = axs[2]
        # ax.plot(30*R_mm_day, label='Recharge', c='dodgerblue', lw=2)
        # ax.set_title('SIM2 Reanalysis', fontsize=8)
        ax.plot(30*R_mm_day_filt, label='Recharge', c='dodgerblue', lw=2)
        ax.set_title('SAFRAN-ISBA', fontsize=8)
        ax.set_ylabel('R [mm/month]')

        ax.set_xlabel('Date')

        # Save plot as PNG
        fig.tight_layout()

    #%% ---- MODELING

    #%% VERSION

    vers = 'TRANS1'

    #%% IMPORT

    # iD_set_simulations = vers

    # folder = glob.glob(os.path.join(calibration_folder, iD_set_simulations+'*'))
    # pickle_file = glob.glob(folder[0]+'/'+'results_'+vers+'*.pkl')[0]
    # with open(pickle_file, 'rb') as f:
    #     d = pickle.load(f)
    # list_model_name = d['list_model_name'][:]
    # list_model_modflow = d['list_model_modflow'][:]

    # model_name = list_model_name[0]
    # model_modflow = list_model_modflow[0]

    #%% A - MODFLOW

    workspace.calibration_folder = calibration_folder

    box = True # or False
    sink_fill = False # or True
    # first_clim = 'mean' # or 'first or value
    plot_cross = True
    cross_ylim = [0,150]
    check_grid = True

    # Recharge
    # rec = R_mm_day
    # run = r_mm_day
    rec = R_mm_day_filt[:] / 1000
    run = rec * 0.1
    # Read first_clim from [flow.sinks_sources.recharge] in config.toml so
    # the policy can be changed without modifying this script.
    _rech_cfg = flow.sinks_sources.get("recharge")
    first_clim = _rech_cfg.first_clim if _rech_cfg is not None else "mean"
    climatic.update_first_clim(first_clim)
    climatic.update_recharge(rec, sim_state=flow.flow_regime)
    climatic.update_runoff(run, sim_state=flow.flow_regime)

    # Fixed
    setting.update_box_model(box)
    setting.update_sink_fill(sink_fill)

    alpha = 15 # in m
    the_K0 = 5e-5*24*3600
    the_sy0 = 2/100

    # Change

    model_name = f"{vers}_K{the_K0/24/3600:.1e}_a{alpha:.1f}_Sy{the_sy0*100:.1f}"
    print(model_name)

    setting.update_model_name(model_name)

    setting.update_check_model(check_grid=check_grid)

    # Inject recharge into flow (process-level) before pre_processing.
    flow.set_recharge(FlowRechargeConfig(
        values=climatic.recharge,
        first_clim=climatic.first_clim,
    ))

    model_folder = workspace.simulations_folder
    preprocess_options = ModflowPreprocessOptions(
        box=setting.box,
        sink_fill=setting.sink_fill,
        check_grid=setting.check_grid,
    )
    if solver_engine == SolverEngine.MODFLOW_NWT:
        model_modflow = Modflow(
            geographic,
            # Workflow settings
            model_folder=model_folder,   # self.simulations_folder
            model_name=setting.model_name,
            bin_path=workspace.bin_path,
            modflow_config=cfg.modflownwt,
            preprocess_options=preprocess_options,
        )
    else:
        model_modflow = Modflow6(
            geographic,
            # Workflow settings
            model_folder=model_folder,   # self.simulations_folder
            model_name=setting.model_name,
            bin_path=workspace.bin_path,
            modflow_config=cfg.modflow6,
            preprocess_options=preprocess_options,
        )

    model_modflow.pre_processing(
        flow=flow,
        domain=domain,
        options=ModflowPreprocessOptions(
            box=setting.box,
            sink_fill=setting.sink_fill,
            check_grid=setting.check_grid,
        ),
    ) # verbose

    list_model_name = []
    list_model_name.append(model_name)
    list_model_modflow = []
    list_model_modflow.append(model_modflow)

    dictio = {}
    dictio['list_model_name'] = list_model_name
    dictio['list_model_modflow'] = list_model_modflow
    pickle_file = os.path.join(workspace.simulations_folder, model_name, 'results_'+model_name+'.pkl')
    with open(pickle_file, 'wb') as f:
        pickle.dump(dictio, f)

    success_model = model_modflow.processing(
        options=ModflowRunOptions(
            write_model=True,
            run_model=True,
            link_mt3dms=True,
        )
    )

    if success_model == True:
        model_modflow.post_processing(
            options=ModflowPostprocessOptions(
                watertable_elevation=True,
                seepage_areas=True,
                outflow_drain=True,
                accumulation_flux=True,
                watertable_depth=True,
                groundwater_flux=False,
                groundwater_storage=False,
                intermittency_weekly=False,
                intermittency_monthly=True,
                intermittency_yearly=False,
                export_all_tif=False,
            )
        )

    timeseries_results = timeseries.Timeseries(geographic,
                                            model_modflow=model_modflow,
                                            runoff=climatic.runoff,
                                            model_modpath=None,
                                            model_mt3dms=None,
                                            datetime_format=True,
                                            subbasin_results=True,
                                            intermittency_weekly=False,
                                            intermittency_monthly = True,
                                            intermittency_yearly=False) # or None

    iter_results = MatchingStreams(geographic, hydrography, workspace, iteration_label=model_name, from_calib=False)

    # obs_to_sim = gpd.read_file(os.path.join(workspace.calibration_folder, model_name, '_matchingstreams','obs_pt.shp'))
    # obs_to_simf = gpd.read_file(os.path.join(workspace.calibration_folder, model_name, '_matchingstreams','obs_ptf.shp'))
    # obsf_to_sim = gpd.read_file(os.path.join(workspace.calibration_folder, model_name, '_matchingstreams','obsflow.shp'))
    obsf_to_simf = gpd.read_file(os.path.join(workspace.simulations_folder, model_name, '_matchingstreams','obsflowf.shp'))

    # sim_to_obs = gpd.read_file(os.path.join(workspace.calibration_folder, model_name, '_matchingstreams','sim_pt.shp'))
    # sim_to_obsf = gpd.read_file(os.path.join(workspace.calibration_folder, model_name, '_matchingstreams','sim_ptf.shp'))
    # simf_to_obs = gpd.read_file(os.path.join(workspace.calibration_folder, model_name, '_matchingstreams','simflow.shp'))
    simf_to_obsf = gpd.read_file(os.path.join(workspace.simulations_folder, model_name, '_matchingstreams','simflowf.shp'))

    # mean_obs_to_sim = np.nanmean(obs_to_sim[obs_to_sim['VALUE1']>=0]['VALUE1'])
    # mean_obs_to_simf = np.nanmean(obs_to_simf[obs_to_simf['VALUE1']>=0]['VALUE1'])
    # mean_obsf_to_sim = np.nanmean(obsf_to_sim[obsf_to_sim['VALUE1']>=0]['VALUE1'])
    mean_obsf_to_simf = np.nanmean(obsf_to_simf[obsf_to_simf['VALUE1']>=0]['VALUE1'])

    # mean_sim_to_obs = np.nanmean(sim_to_obs[sim_to_obs['VALUE1']>=0]['VALUE1'])
    # mean_sim_to_obsf = np.nanmean(sim_to_obsf[sim_to_obsf['VALUE1']>=0]['VALUE1'])
    # mean_simf_to_obs = np.nanmean(simf_to_obs[simf_to_obs['VALUE1']>=0]['VALUE1'])
    mean_simf_to_obsf = np.nanmean(simf_to_obsf[simf_to_obsf['VALUE1']>=0]['VALUE1'])

    ### vf simf/obsf - with : gap=0.5, streams : RNF, rec : 1000 (year) ==> isba
    obs = mean_obsf_to_simf
    sim = mean_simf_to_obsf
    indicator = sim/obs

    #%% PLOT CROSS-SECTION
    if display_plots:
        fig, ax = plt.subplots(1, 1, figsize=(6,4), dpi=300)
        print(stable_folder)

        mask = imageio.imread(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))
        watertable_elevation = np.load(os.path.join(simulations_folder, model_name, '_postprocess', 'watertable_elevation.npy'), allow_pickle=True).item()

        dem_data = imageio.imread(geographic.watershed_dem)
        wt_data = watertable_elevation[2]

        xvalues = np.linspace(-1,1,dem_data.shape[1])
        yvalues = np.linspace(-1,1,dem_data.shape[0])
        xx, yy = np.meshgrid(xvalues,yvalues)

        cur_x = dem_data.shape[1] /2
        cur_x = 50

        wt_prof = wt_data.astype(float)
        wt_prof[wt_prof<0] = np.nan
        dem_max = dem_data.max()
        dem_prof = dem_data.astype(float)
        dem_prof[dem_prof<0] = np.nan
        dem_plot = np.ma.masked_array(dem_data, mask=(dem_data<0))
        dem_v_plot = dem_prof[:,int(cur_x)]
        dem_v_plot[dem_v_plot == 0] = np.nan
        wt_v_plot = wt_prof[:,int(cur_x)]
        wt_v_plot[wt_v_plot == 0] = np.nan

        wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, dem_v_plot-20, wt_v_plot, color='dodgerblue', alpha=0.5, lw=0)
        w_prof = ax.plot(np.arange(xx.shape[0])*75, wt_v_plot, color='navy', lw=1.5)
        wt_v_fill = ax.fill_between(np.arange(xx.shape[0])*75, wt_v_plot, dem_v_plot, color='saddlebrown', alpha=0.5, lw=0)
        d_prof = ax.plot(np.arange(xx.shape[0])*75, dem_v_plot, 'saddlebrown', lw=1.5)
        ax.fill_between(np.arange(xx.shape[0])*75, 0, dem_v_plot-20, color='lightgrey', alpha=0.5, lw=0)
        ax.plot(np.arange(xx.shape[0])*75, dem_v_plot-20, color='dimgray', lw=1.5)

        ax.set_xlim(1500, 4900)
        ax.set_ylim(90, 130)
        ax.set_yticks([90,100,110,120,130])
        ax.set_xlabel('Distance [m]')
        ax.set_ylabel('Elevation [m]')

        plt.tight_layout()

        # fig.savefig(out_path+'/'+watershed_name+'/results_simulations/'+model_name+'/_postprocess/_figures/'+'2D_cross.png', dpi=300, bbox_inches='tight')

    #%% PLOT STREAMFLOW

    area = int(round(geographic.catch_area))

    Qobs_path = data_path / 'Debit_Exu_Kervidy_Aghrys_LJr_2024-04.txt'
    Qobs = pd.read_csv(Qobs_path, sep=';', header=None)
    date = pd.to_datetime(Qobs[0]+' '+Qobs[1], format="%d/%m/%Y %H:%M:%S")
    Qobs.index = date
    Qobs = Qobs[2].to_frame(name="Q")
    Qobs = Qobs / 1000 # L/d to m3/d
    Qobs = (Qobs / (area*1000000)) # m3/d to m/day
    Qobs = Qobs.resample('ME').mean()
    # Qobs = Qobs.resample('M').sum() * 1000 # m/day to mm/month
    # Qobs = select_period(Qobs, 2003, 2003)
    Qobs = Qobs * 30 * 1000

    simul_list = sorted(glob.glob(os.path.join(simulations_folder,vers+'*')), key=os.path.getmtime)

    if display_plots:
        for i, simul in enumerate(simul_list[:]):

            fig, (a0) = plt.subplots(1, 1, figsize=(12,3.5), dpi=300)

            model_name = os.path.split(simul)[-1]

            Smod_path = os.path.join(simul, r'_postprocess/_timeseries/_simulated_timeseries.csv')
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)

            Rmod = Smod['recharge'] * 30 * 1000
            rmod = Smod['runoff'] * 30 * 1000

            Omod = (Smod['outflow_drain'] * 30 * 1000)
            Qmod = Omod + rmod

            ax = a0
            ax.plot(Qobs, color='k', lw=2, ls='-', zorder=0, label='Observed')
            # ax.fill_between(Omod.index, Omod, Qmod, color='red', lw=1, label='Simualted : outflow + runoff', alpha=0.5)
            # ax.plot(Omod, color='red', lw=2, label='Simulated: outflow')
            ax.plot(Qmod, color='red', lw=2, label='Simulated: outflow')
            ax.plot(Rmod, color='dodgerblue', lw=2, ls='-', zorder=0, label='Recharge')
            ax.set_xlabel('Date')
            ax.set_ylabel('Q / A [mm/month]')
            # ax.set_yscale('log')
            ax.xaxis.set_major_locator(mdates.YearLocator(1))
            ax.xaxis.set_minor_locator(mdates.MonthLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
            ax.set_xlim(pd.to_datetime('2002'), pd.to_datetime('2005'))
            ax.legend(loc='upper left')
            ax.set_title(model_name.upper(), fontsize=10)
            ax.set_ylim(-5,100)

    #%% PLOT PIEZOMETRY

    # Qobs_path = data_path + 'Debit_Exu_Kervidy_Aghrys_LJr_2024-04.txt'
    # Qobs = pd.read_csv(Qobs_path, sep=';', header=None)
    # date = pd.to_datetime(Qobs[0]+' '+Qobs[1], format="%d/%m/%Y %H:%M:%S")
    # Qobs.index = date
    # Qobs = Qobs[2].to_frame(name="Q")
    # Qobs = Qobs / 1000 # L/d to m3/d
    # Qobs = (Qobs / (area*1000000)) # m3/d to m/day
    # Qobs = Qobs.resample('W').mean()
    # # Qobs = Qobs.resample('M').sum() * 1000 # m/day to mm/month
    # # Qobs = select_period(Qobs, 2003, 2003)
    # Qobs = Qobs * 7 * 1000

    simul_list = sorted(glob.glob(os.path.join(simulations_folder,vers+'*')), key=os.path.getmtime)
    if display_plots:
        for i, simul in enumerate(simul_list[:]):


            model_name = os.path.split(simul)[-1]

            Smod_path = os.path.join(simul, r'_postprocess/_timeseries/_simulated_timeseries.csv')
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)

            Rmod = Smod['recharge'] * 30 * 1000

            WTEmod = Smod['watertable_elevation']
            WTDmod = Smod['watertable_depth']

            fig, (a0) = plt.subplots(1, 1, figsize=(12,3.5), dpi=300)

            ax = a0
            # ax.plot(Qobs, color='k', lw=2, ls='-', zorder=0, label='Observed')
            # ax.fill_between(Omod.index, Omod, Qmod, color='red', lw=1, label='Simualted : outflow + runoff', alpha=0.5)
            ax.plot(WTDmod, marker='o', color='red', lw=2, label='Simulated: watertable')
            # ax.plot(Rmod, color='dodgerblue', lw=2, ls='-', zorder=0, label='Recharge')
            ax.set_xlabel('Date')
            ax.set_ylabel('WT depth [m]')
            ax.xaxis.set_major_locator(mdates.YearLocator(1))
            ax.xaxis.set_minor_locator(mdates.MonthLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
            ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
            ax.legend(loc='upper left')
            ax.set_title(model_name.upper(), fontsize=10)
            ax.set_ylim(0,None)
            ax.invert_yaxis()

            axb = ax.twinx()
            axb.bar(Rmod.index, Rmod, color='dodgerblue', width=10, edgecolor='None', lw=0, alpha=1, label='Recharge')
            axb.set_ylim(0,100)
            axb.invert_yaxis()
            axb.set_yticklabels([0,100])
            axb.legend(loc='upper right')

    #%% B - MODPATH

    model_modpath = None

    if solver_engine != SolverEngine.MODFLOW_NWT:
        print("MODPATH workflow is currently available only with solver_engine='modflownwt'. Skipping section B.")
    else:

        list_folder = glob.glob(os.path.join(str(workspace.simulations_folder), vers+'*'))

        model_name = list_folder[0].split(os.path.sep)[-1]

        pickle_file = list_folder[0] + '/' + 'results_' + model_name + '.pkl'
        with open(pickle_file, 'rb') as f:
            d = pickle.load(f)

        list_model_name = d['list_model_name'][:]
        list_flow_model = d['list_model_modflow'][:]

        model_modflow = list_flow_model[0]

        # Prepare particle tracking from seepage inside the catchment studied
        tif_seep = os.path.join(workspace.simulations_folder, model_name, '_postprocess/_rasters','seepage_areas_t(0).tif')
        tif_seep_clip = os.path.join(workspace.simulations_folder, model_name, '_postprocess/_rasters','seepage_areas_t(0)_clip.tif')
        wbt.clip_raster_to_polygon(
            tif_seep,
            os.path.join(workspace.stable_folder, 'geographic', 'watershed.shp'),
            tif_seep_clip,
            maintain_dimensions=True)

        particle_params = cfg.transport.modpath.parameters.model_dump()
        if particle_params.get('zone_partic') == 'seepage_clip':
            particle_params['zone_partic'] = tif_seep_clip
        transport.modpath.set_parameters(particle_params)

        model_modpath = Modpath(domain,
                        transport,
                        model_modflow,
                        # Frame settings
                        model_folder = model_folder,
                        model_name = model_modflow.model_name,
                        bin_path = workspace.bin_path)

        # Preprocessing Modflow
        model_modpath.pre_processing() # verbose
        success_model = model_modpath.processing(write_model=True, run_model=True)
        model_modpath.post_processing(model_modpath,
                    ending_point=True,
                    starting_point=True,
                    pathlines_shp=True,
                    particles_shp=True,
                    random_id=None, # select randomly to save (for pathlines and particles)
                    ) # None

        model_modpath.filt_processing(model_modpath,
                    norm_flux=True, # for forward only
                    filt_time=True, # delete particles with time at 0, add a column with time divided by 365 (considering recharge in days)
                    filt_seep=True, # only forward, keep only particles finishing in zone1 (seepage), keep only particles finishing in k1 (first layer)
                    filt_inout=True, # delete particles in and out in the same cell (first layer)
                    calc_rtd=False, # compute residence time distribution
                    random_id=None, # select randomly to keep
                    ) # None

    #%% PLOT PATHLINES

    if solver_engine == SolverEngine.MODFLOW_NWT:
        shp_pathlines = gpd.read_file(os.path.join(simulations_folder, model_name, '_postprocess', '_particles', 'pathlines_weighted.shp'))
        shp_endpoints = gpd.read_file(os.path.join(simulations_folder, model_name, '_postprocess', '_particles', 'starting_weighted.shp'))

        line = gpd.read_file(os.path.join(stable_folder, 'geographic', 'watershed.shp'))

        dem_rio = rasterio.open(geographic.watershed_box_buff_dem)
        dem_data = dem_rio.read(1)
        dem_data = np.ma.masked_where(dem_data < 0, dem_data)

        norm = mcolors.LogNorm(vmin=0.1, vmax=100)
        im = cm.ScalarMappable(cmap='jet', norm=norm)
        im.set_array([])

        if display_plots:
            fig, ax = plt.subplots(1,1, figsize=(8,6))

            # Base raster and layers
            rasterio.plot.show(dem_data, ax=ax, transform=dem_rio.transform,
                            cmap='Greys', alpha=0.7, zorder=-10)

            shp_pathlines.plot(ax=ax, column='time_win_y', cmap='jet', lw=1,
                            norm=norm, zorder=1)

            shp_endpoints.plot(ax=ax, column='time_win_y', cmap='jet', lw=0.5, markersize=20,
                                    legend=False, norm=norm, zorder=2, edgecolor='k')

            line.plot(ax=ax, facecolor='None', edgecolor='k', lw=2, zorder=-1)

            # Title
            ax.set_title('Residence times - backward from seepage [y]', fontsize=10)

            # Colorbar on the right, same height
            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="5%", pad=0.1)
            cbar = fig.colorbar(im, cax=cax, orientation='vertical')

            fig.tight_layout()

            # fig.savefig(os.path.join(simulations_folder, model_name,
            #                             '_postprocess', '_figures', 'RTD_'+model_name+'.png'))

    #%% PLOT 2D / 3D

    if solver_engine == SolverEngine.MODFLOW_NWT:
        visu = visualization_results.Visualization(workspace, geographic, hydrography, model_name)
        if display_plots:
            visu.visual2D(object_list = [
                                    'map',
                                    'grid',
                                    'watertable',
                                    'watertable_depth',
                                    'drain_flow',
                                    'surface_flow',
                                    'pathlines',
                                    'residence_times'
                                    ],
                    color_scale = [
                                    (None,None),
                                    (None,None),
                                    (None,None),
                                    (None,None),
                                    (None,None),
                                    (None,None),
                                    (0,10),
                                    (0,10),
                                    ],
                                    lines=1000
                                    )

        export_vtuvtk.VTK(workspace,geographic, hydrography, model_name)
        if display_3D==True:
            visu = visualization_results.Visualization(workspace,geographic, hydrography, model_name)
            if display_plots:
                visu.visual3D(interactive=True, object_list=[
                                                        'grid',
                                                        'watertable',
                                                        'watertable_depth',
                                                        'surface_flow',
                                                        'drain_flow',
                                                        'pathlines'
                                                        ],
                                                        view='south-west',
                                                        # view='north',
                                                        lines=None,
                                                        cloc=(0.7,0.1),
                                                        z_scale=10)
    else:
        print("Skipping MODPATH-based 2D/3D visualizations and VTK export for solver_engine='mf6'.")

    #%% C - MT3DMS

    list_folder = glob.glob(os.path.join(str(workspace.simulations_folder), vers+'*'))

    model_name = list_folder[0].split(os.path.sep)[-1]

    pickle_file = list_folder[0] + '/' + 'results_' + model_name + '.pkl'
    with open(pickle_file, 'rb') as f:
        d = pickle.load(f)

    list_model_name = d['list_model_name'][:]
    list_flow_model = d['list_model_modflow'][:]

    model_modflow = list_flow_model[0]

    model_mt3dms = None
    nper = model_modflow.nper
    if solver_engine == SolverEngine.MODFLOW_NWT:
        nlay = model_modflow.mf.nlay
        nrow = model_modflow.mf.nrow
        ncol = model_modflow.mf.ncol
    else:
        nlay = model_modflow.nlay
        nrow = model_modflow.nrow
        ncol = model_modflow.ncol

    sconc_init = np.ones((nlay, nrow, ncol)) * (100/1000) # 50 mg/L en kg/m3
    sconc_input = {i: np.ones((nrow, ncol)) * (50/1000) for i in range(nper)}
    sconc_input = dict(islice(sconc_input.items(), 1, None))
    rate_decay = np.ones((nlay, nrow, ncol)) * (1/(2*365))

    transport.mt3dms.set_parameters(
                    cfg.transport.mt3dms.parameters.model_dump()
                    )
    transport.mt3dms.set_parameters(
                    spc_name='NO3',
                    sconc_init=sconc_init,          # array of (nlay, nrow, ncol)
                    sconc_input=sconc_input,         # dictionnray [time] with array of (nlay, nrow, ncol)
                    rate_decay=rate_decay,          # array of (nlay, nrow, ncol), unit T-1
                    )
    transport.modflow6gwt.set_parameters(
                    cfg.transport.modflow6gwt.parameters.model_dump()
                    )
    transport.modflow6gwt.set_parameters(
                    spc_name='NO3',
                    sconc_init=sconc_init,          # array of (nlay, nrow, ncol)
                    sconc_input=sconc_input,         # dictionnray [time] with array of (nlay, nrow, ncol)
                    rate_decay=rate_decay,          # array of (nlay, nrow, ncol), unit T-1
                    )

    scenario = 's1'
    suffix_name = '_mt_'+scenario
    if solver_engine == SolverEngine.MODFLOW_NWT:
        model_mt3dms = Mt3dms(domain,
                            transport,
                            model_modflow,
                            # Frame settings
                            model_folder = model_folder,
                            model_name = model_modflow.model_name,
                            suffix_name = suffix_name,
                            bin_path = workspace.bin_path)
        model_mt3dms.pre_processing()


        success_mt3dms = model_mt3dms.processing(write_model=True, run_model=True, verbose=True)

        pp_model = model_mt3dms.post_processing(model_mt3dms,
                                concentration_seepage=True,
                                mass_seepage=True,
                                mass_accumulated=True,
                                export_all_tif=True) # None

        timeseries_results = timeseries.Timeseries(geographic,
                                                    model_modflow=model_modflow,
                                                    runoff=climatic.runoff,
                                                    model_modpath=model_modpath,
                                                    model_mt3dms=model_mt3dms,
                                                    suffix_name=scenario,
                                                    datetime_format=True,
                                                    subbasin_results=True,
                                                    intermittency_weekly=False,
                                                    intermittency_monthly = True,
                                                    residence_times=True,
                                                    concentration_seepage=True,
                                                    mass_accumulated=True
                                                    ) # or None
    else:
        model_mt3dms = Modflow6Transport(domain,
                            transport,
                            model_modflow,
                            # Frame settings
                            model_folder = model_folder,
                            model_name = model_modflow.model_name,
                            suffix_name = suffix_name,
                            bin_path = workspace.bin_path)
        model_mt3dms.pre_processing()


        success_mt3dms = model_mt3dms.processing(write_model=True, run_model=True, verbose=True)

        if success_mt3dms:
            pp_model = model_mt3dms.post_processing(model_mt3dms,
                                    concentration_seepage=True,
                                    mass_seepage=True,
                                    mass_accumulated=False,
                                    export_all_tif=True) # None

            timeseries_results = timeseries.Timeseries(geographic,
                                                       model_modflow=model_modflow,
                                                        runoff=climatic.runoff,
                                                        model_modpath=model_modpath,
                                                        model_mt3dms=model_mt3dms,
                                                        suffix_name=scenario,
                                                        datetime_format=True,
                                                        subbasin_results=True,
                                                        intermittency_weekly=False,
                                                        intermittency_monthly = True,
                                                        residence_times=True,
                                                        concentration_seepage=True,
                                                        mass_accumulated=False
                                                        ) # or None
        else:
            print("MF6 transport run failed, skipping transport post-processing.")

    #%% PLOT CONCENTRATION

    if display_plots and solver_engine == SolverEngine.MODFLOW_NWT:
        # CrÃ©er le GIF Ã  la fin du processus
        vgif_name = vers
        gif_name = vgif_name+'.gif'

        plot_gif = True

        input_no3 = model_mt3dms.sconc_input[1].mean() * 1000

        ### USEFUL LINKS
        # https://www2.hawaii.edu/~jonghyun/classes/S18/CEE696/files/11_flopy_mt3dms_transport_modeling.pdf
        # https://download.feflow.com/html/help72/feflow/09_Parameters/Auxiliary_Data/peclet_number.html
        # https://flopy.readthedocs.io/en/3.4.2/Notebooks/mt3dms_examples.html#

        ucnobj  = bf.UcnFile(model_modflow.full_path + '/' + model_mt3dms.model_name_mt+'.UCN')
        concobj_1c = ucnobj.get_alldata(mflay=None) # 4D:[time, lay, row, col]

        concobj_1c_fil = concobj_1c.copy() * 1000
        concobj_1c_fil[concobj_1c_fil>=1e30] = np.nan
        concobj_1c_fil = concobj_1c_fil[:]

        concobj_1c_fil_surf = {}

        the_mins = []
        the_maxs = []

        # Boucle sur chaque pas de temps
        # for i in range(len(concobj_1c_fil)):
        for i in range((model_mt3dms.model_modflow.nper)):
            the_time = i
            # print(i)
            # try:
            seep = imageio.imread(os.path.join(model_modflow.full_path, f'_postprocess/_rasters/outflow_drain_t({int(the_time)}).tif'))
            # except:
            #     continue
            concobj_1c_fil_surf[the_time] = concobj_1c_fil[the_time+1][0]
            concobj_1c_fil_surf[the_time] = np.ma.masked_where(seep <= 0, concobj_1c_fil_surf[the_time])
            # concobj_1c_fil[the_time][0][concobj_1c_fil[the_time][0] <= 0] = np.nan

            the_mins.append(np.nanmin(concobj_1c_fil_surf[the_time]))
            the_maxs.append(np.nanmax(concobj_1c_fil_surf[the_time]))

        the_min = np.nanmin(the_mins)
        the_max = np.nanmax(the_maxs)

        concobj_1c_fil_surf = dict(list(concobj_1c_fil_surf.items())[:])

        # Liste pour accumuler les boxplots prÃ©cÃ©dents
        all_box_stats = []

        # DÃ©finir le rÃ©pertoire de sauvegarde des images
        figures_dir = os.path.join(str(simulations_folder), '_figures/')
        if not os.path.exists(figures_dir):
            os.makedirs(figures_dir)

        mean_vals = []
        mean_times = []

        wbt.hillshade(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'), os.path.join(stable_folder, 'geographic', 'watershed_hill.tif'))

        dem = rasterio.open(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))
        hill = rasterio.open(os.path.join(stable_folder, 'geographic', 'watershed_hill.tif'))

        # Boucle sur chaque pas de temps
        for i in range(len(concobj_1c_fil_surf)):
            the_time = i

            conc_plt = concobj_1c_fil_surf[i]

            xi = conc_plt.flatten()
            xi = xi[~np.isnan(xi)]

            # xpos = mdates.date2num(R_mm_day.index[i])
            xpos = mdates.date2num(R_mm_day_filt.index[i])

            if xi.size == 0:
                continue

            q10 = np.nanmin(xi)
            q90 = np.nanmax(xi)
            median = np.nanmedian(xi)
            mean = np.nanmean(xi)

            box_stats = [{
                'med': median,
                'mean': mean,
                'q1': q10,
                'q3': q90,
                'whislo': q10,
                'whishi': q90,
                'fliers': []
            }]

            mean_vals.append(mean)
            mean_times.append(xpos)

            # Ajouter les boxplots cumulÃ©s Ã  chaque itÃ©ration
            all_box_stats.append((xpos, box_stats))  # Conserver les rÃ©sultats des boxplots prÃ©cÃ©dents

            # CrÃ©er une nouvelle figure et des axes Ã  chaque itÃ©ration
            fig, axs = plt.subplots(2, 1, figsize=(8, 12), dpi=300, gridspec_kw={'height_ratios': [1, 3]})
            ax = axs.ravel()

            # Graphique du boxplot et de la recharge (subplot du haut)
            axb = ax[0].twinx()

            ax[0].zorder = 1
            axb.zorder = 0 # fills in back
            ax[0].patch.set_visible(False)

            # Ajouter les boxplots prÃ©cÃ©dents et actuels Ã  la figure
            for xpos, box_stat in all_box_stats:
                ax[0].bxp(box_stat, positions=[xpos], widths=5, showfliers=False,
                        showmeans=True, meanline=False,
                        boxprops=dict(color='forestgreen', alpha=1, linewidth=1),
                        medianprops=dict(color='forestgreen', linewidth=1),
                        meanprops=dict(marker='o', markerfacecolor='k', markeredgecolor='k', markersize=5),
                        whiskerprops=dict(linestyle='-', linewidth=0),
                        capprops=dict(linewidth=0),
                        zorder=1)  # low zorder â†’ in background

            # Mettre Ã  jour la ligne verticale du premier graphique
            ax[0].axvline(x=xpos, color='black', linestyle='--', lw=0.5, zorder=-1)

            ax[0].axhline(y=input_no3, color='darkorange', linestyle='-', lw=1, zorder=-1,
                        label='Injection: 50 mg/L \nNO3 decay : 1/2 y$^{-1}$ \nDispersivity: 5 m longi., 0.5 m trans h., 0.05 m trans v. \nDiffusion: 10$^{-10}$ mÂ²/s',
                        )

            # if i==0:
            ax[0].legend(loc='upper center', frameon=False)

            # RÃ©glages pour le graphique de concentration
            ax[0].set_ylabel('[NO3] mg/L', color='forestgreen')
            ax[0].set_title('Synthetic drought year - Initial: mean recharge and aquifer at 100 mg/L', fontsize=10)
            ax[0].xaxis.set_major_locator(mdates.MonthLocator(bymonthday=1))
            ax[0].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            ax[0].tick_params(axis='x', labelrotation=90, labelsize=8)
            ax[0].set_ylim(30, 100)

            # Line connectant les moyennes
            ax[0].plot(mean_times, mean_vals, color='black', lw=2, linestyle='-', zorder=2)

            # Placer la recharge en arriÃ¨re-plan du graphique
            # axb.step(R_mm_day.index, R_mm_day * 30, lw=2, color='dodgerblue', zorder=0)
            axb.step(R_mm_day_filt.index, R_mm_day_filt * 30, lw=2, color='dodgerblue', zorder=0)
            axb.set_ylabel('Recharge [mm/month]', color='dodgerblue')

            ax[0].set_xlim(pd.to_datetime('01-2003'), pd.to_datetime('01-2004'))

            # New xi
            xi = conc_plt.copy()

            # CrÃ©er un graphique avec la carte
            norm = mcolors.LogNorm(vmin=30, vmax=100)
            color_camp = 'turbo'
            sm = cm.ScalarMappable(cmap=color_camp, norm=norm)
            sm.set_array([])

            rasterio.plot.show(np.ma.masked_where(hill.read(1) < 0, hill.read(1)),
                            ax=ax[1], transform=hill.transform,
                            cmap='Greys_r', alpha=0.75, zorder=-10,
                            )

            rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, xi),
                            ax=ax[1], transform=dem.transform,
                            cmap=color_camp, alpha=1, zorder=1,
                            # norm=norm
                            )

            # Ajouter les limites du bassin versant
            shp_bv = gpd.read_file(geographic.watershed_shp)
            shp_hydro = gpd.read_file(hydrography.streams)
            shp_bv.plot(ax=ax[1], facecolor='None', lw=3, zorder=2)
            shp_hydro.plot(ax=ax[1], color='navy', lw=1, zorder=0)

            divider = make_axes_locatable(ax[1])
            cax = divider.new_vertical(size='5%', pad=0.6, pack_start=True)
            fig.add_axes(cax)
            cbar = fig.colorbar(sm, cax=cax, orientation='horizontal', label='[NO3]')
            cbar.ax.set_xticks([30, 50, 70 ,100])
            cbar.ax.set_xticklabels([30, 50, 70, 100])  # (facultatif) si tu veux formater les labels
            fig.tight_layout()

            # Sauvegarder la figure pour ce temps
            fig.tight_layout()
            fig.savefig(figures_dir+vgif_name+'_'+str(i)+'_'+model_name+'.png', dpi=300, bbox_inches='tight')

            # Fermer la figure pour Ã©conomiser de la mÃ©moire
            if i < (len(concobj_1c_fil_surf)-1):
                plt.close(fig)
            else:
                plt.show()

        if plot_gif == True:
            # CrÃ©er le GIF Ã  partir des images enregistrÃ©es
            begin_by = figures_dir + vgif_name
            filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)
            images = []
            for filename in filenames:
                images.append(imageio.imread(filename))
            ### Method 1
            # imageio.mimsave(figures_dir + '_' + gif_name, images, duration=0.5, loop=0, format='GIF-PIL')
            image_paths = filenames
            images = [Image.open(img) for img in image_paths]
            ### Method 2
            images[0].save(figures_dir + '_' + gif_name, save_all=True, append_images=images[1:], optimize=True, duration=200, loop=0)

        #%% PLOT INTERACTIVE

        # CLICK on the map to select a cross-section !
        dem_data = imageio.imread(os.path.join(stable_folder,'geographic','watershed_box_buff_dem.tif')) # dem data
        stream_data = imageio.imread(os.path.join(stable_folder,'hydrography','botopage2024_naizin_streams_perennial-intermittent.tif')) # river data
        watertable_data = imageio.imread(os.path.join(simulations_folder,model_name,'_postprocess/_rasters/','watertable_elevation_t(0).tif')) # watertable data
        interactive = True
        visu = visualization_results.Visualization(workspace, geographic, hydrography, model_name)
        visu.interactive_cross_section(dem_data, watertable_data, stream_data, interactive)

        #%% WEB ANIMATION

        import plotly.graph_objects as go
        import base64
        from io import BytesIO

        # Exemple : crÃ©ation de la liste des fichiers
        figures_dir = os.path.join(str(simulations_folder), '_figures/')
        begin_by = figures_dir + vers
        filenames = sorted(glob.glob(begin_by+'*.png'), key=os.path.getmtime)

        # Charger toutes les images en base64
        def image_to_base64(path):
            with Image.open(path) as img:
                with BytesIO() as stream:
                    img.save(stream, format="png")
                    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("utf-8")

        image_sources = [image_to_base64(p) for p in filenames]

        if not image_sources:
            raise FileNotFoundError(f"No PNG files matching {begin_by}*.png were found")

        base_image = dict(
            source=image_sources[0],
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            sizex=1,
            sizey=1,
            xanchor="center",
            yanchor="middle",
            sizing="contain"
        )

        frames = [
            go.Frame(
                name=str(i),
                layout=go.Layout(images=[dict(base_image, source=src)])
            )
            for i, src in enumerate(image_sources)
        ]

        # PremiÃ¨re image (affichÃ©e par dÃ©faut)
        fig = go.Figure(
            layout=go.Layout(
                title="Slider to navigate between images",
                images=[base_image],
                updatemenus=[dict(
                    type="buttons",
                    showactive=False,
                    y=1.05,
                    x=1.15,
                    xanchor="right",
                    yanchor="top",
                    buttons=[
                        dict(label="Play", method="animate", args=[None, {"frame": {"duration": 500, "redraw": True}, "fromcurrent": True}]),
                        dict(label="Pause", method="animate", args=[[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}])
                    ]
                )],
                sliders=[{
                    "steps": [
                        {
                            "method": "animate",
                            "args": [[str(k)], {"mode": "immediate", "frame": {"duration": 0, "redraw": True}}],
                            "label": f"{k+1}"
                        } for k in range(len(image_sources))
                    ],
                    "transition": {"duration": 0},
                    "x": 0.5,
                    "xanchor": "center",
                    "y": -0.01,
                    "yanchor": "top",
                    "len": 0.85,
                    "pad": {"t": 40}
                }]
            ),
            frames=frames
        )

        fig.update_layout(
            width=1600,
            height=900,
            margin=dict(l=60, r=60, t=60, b=90),  # Small margins for spacing
        )

        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)

        fig.show("browser")

#%% ---- END OF SCRIPT

#%% ---- NOTES


