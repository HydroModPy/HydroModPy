# -*- coding: utf-8 -*-
"""
Parallelized automatic calibration system for HydroModPy
"""
#* Pour lancer la calibration passer par le terminale de commande , activer l'environnement HydroModPy (hydromodpy-0.1), aller dans le dossier de ce fichier et taper la commande ipython .\param_multi_core.py
import os
import sys
import pandas as pd
import numpy as np
import multiprocessing as mp
from pathlib import Path
import shutil
import time
from datetime import datetime
import logging

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(processName)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('calibration_log.log'),
        logging.StreamHandler()
    ]
)

def setup_worker_environment(worker_id, base_config):
    """
    Configure the environment for a specific worker.
    
    Parameters
    ----------
    worker_id : int
        Unique identifier for the worker
    base_config : dict
        Base configuration dictionary
        
    Returns
    -------
    dict
        Worker-specific configuration with updated paths
    """
    # Create unique temporary folder for this worker
    worker_temp_dir = os.path.join(base_config['temp_base_dir'], f'worker_{worker_id}')
    os.makedirs(worker_temp_dir, exist_ok=True)
    
    # Adapt paths for this worker
    worker_config = base_config.copy()
    worker_config['out_path'] = worker_temp_dir
    worker_config['worker_id'] = worker_id
    
    return worker_config

def run_single_simulation(hk, sy, base_config, iteration_name):
    """
    Run a single simulation with given parameters.
    
    Parameters
    ----------
    hk : float
        Hydraulic conductivity parameter
    sy : float
        Specific yield parameter  
    base_config : dict
        Base configuration dictionary
    iteration_name : str
        Name for this iteration
        
    Returns
    -------
    dict
        Dictionary containing calculated statistics and success status
    """
    try:
        # Configure Python path for module imports
        import sys
        from os.path import dirname, abspath
        
        # Add root_dir to path
        root_dir = base_config['root_dir']
        if root_dir not in sys.path:
            sys.path.append(root_dir)
        
        # Import necessary modules (in function to avoid multiprocessing conflicts)
        import warnings
        warnings.filterwarnings('ignore', category=DeprecationWarning)
        
        import pkg_resources # Must be placed after DeprecationWarning as it is itself deprecated
        warnings.filterwarnings('ignore', message='.*pkg_resources.*')
        warnings.filterwarnings('ignore', message='.*declare_namespace.*')
        
        # Specific imports
        from src import watershed_root
        from src.display import visualization_watershed
        from src.tools import toolbox
        import deepdish as dd
        import imageio
        import whitebox
        import xarray as xr
        import matplotlib.pyplot as plt
        import geopandas as gpd
        from shapely.ops import nearest_points
        
        # Configure whitebox
        wbt = whitebox.WhiteboxTools()
        wbt.verbose = False
        
        # Configuration for this simulation
        config = base_config.copy()
        config['hk'] = hk
        config['sy'] = sy
        config['model_name'] = iteration_name
        
        # Ensure worker_id is available for logs
        worker_id = config.get('worker_id', 'unknown')
        logging.info(f"Worker {worker_id}: Starting simulation hk={hk}, sy={sy}")
        
        # Create watershed
        watershed_name = '_'.join([
            config['study_site'], 
            str(config['first_year']), 
            str(config['last_year']), 
            config['freq_input'], 
            config['sim_state']
        ])
        
        # Initialize watershed
        BV = watershed_root.Watershed(
            dem_path=config['dem_path'],
            out_path=config['out_path'],
            load=config['load'],
            watershed_name=watershed_name,
            from_xyv=config['from_xyv'],
            save_object=config['save_object']
        )
        
        # Configure folders - IMPORTANT CORRECTION
        BV.calibration_folder = os.path.join(config['out_path'], watershed_name, 'results_calibration')
        
        # MISSING ADDITION: Define simulations_folder for MatchingStreams
        BV.simulations_folder = os.path.join(config['out_path'], watershed_name, 'results_simulations')
        
        # Add geographic data
        BV.add_geology(config['data_path'], types_obs='GEO1M.shp', fields_obs='CODE_LEG')
        BV.add_hydrography(config['data_path'], types_obs=['regional stream network'])
        BV.add_hydrometry(config['data_path'], 'france hydrometric stations.shp')
        
        # Add climatic data
        BV.add_climatic()
        
        # Load climatic data from CSV
        df_climatic = pd.read_csv(
            os.path.join(config['data_path'], config['study_site'], 'Meteo', 'Historiques SIM2', 'climatic_data.csv'), 
            index_col=0, parse_dates=True
        )
        df_climatic.index = pd.to_datetime(df_climatic.index)
        df_climatic = df_climatic.loc[
            (df_climatic.index >= pd.Timestamp(f"01/01/{config['first_year']}")) &
            (df_climatic.index <= pd.Timestamp(f"31/12/{config['last_year']}"))
        ]
        
        agg_dict = {
            'recharge': 'sum', 'runoff': 'sum', 'precip': 'sum',
            'evt': 'sum', 'etp': 'sum', 't': 'mean'
        }
        df_climatic = df_climatic.resample(config['freq_input']).agg(agg_dict)
        
        # Climatic configuration
        BV.climatic.recharge = df_climatic['recharge']
        BV.climatic.runoff = df_climatic['runoff']
        BV.climatic.precip = df_climatic['precip']
        BV.climatic.evt = df_climatic['evt']
        BV.climatic.etp = df_climatic['etp']
        BV.climatic.t = df_climatic['t']
        
        first_clim = 'mean'
        BV.climatic.update_first_clim(first_clim)
        
        # Model configuration
        BV.add_settings()
        BV.add_hydraulic()
        
        # Model parameters
        BV.settings.update_model_name(config['model_name'])
        BV.settings.update_box_model(config['box'])
        BV.settings.update_sink_fill(config['sink_fill'])
        BV.settings.update_simulation_state(config['sim_state'])
        BV.settings.update_check_model(plot_cross=config['plot_cross'])
        
        # Hydraulic parameters (uses hk and sy passed as parameters)
        BV.hydraulic.update_nlay(config['nlay'])
        BV.hydraulic.update_lay_decay(config['lay_decay'])
        BV.hydraulic.update_bottom(config['bottom'])
        BV.hydraulic.update_thick(config['thick'])
        BV.hydraulic.update_hk(hk * 3600 * 24)  # Variable parameter
        BV.hydraulic.update_sy(sy / 100)  # Variable parameter
        BV.hydraulic.update_cond_drain(config['cond_drain'])
        
        # Climatic parameters
        BV.climatic.update_recharge(BV.climatic.recharge, sim_state=config['sim_state'])
        BV.climatic.update_runoff(BV.climatic.runoff, sim_state=config['sim_state'])
        BV.climatic.update_first_clim(first_clim)
        
        # Boundary parameters
        BV.settings.update_bc_sides(config['bc_left'], config['bc_right'])
        BV.add_oceanic(config['sea_level'])
        BV.settings.update_dis_perlen(config['dis_perlen'])
        BV.settings.update_input_particles(zone_partic=BV.geographic.watershed_box_buff_dem)
        
        # Launch MODFLOW simulation
        model_modflow = BV.preprocessing_modflow(for_calib=False)
        success_modflow = BV.processing_modflow(model_modflow, write_model=True, run_model=True)
        
        if not success_modflow:
            return {
                'success': False,
                'error': 'MODFLOW simulation failed'
            }
        
        # Post-processing
        BV.postprocessing_modflow(
            model_modflow,
            watertable_elevation=True,
            watertable_depth=True,
            seepage_areas=True,
            outflow_drain=True,
            groundwater_flux=True,
            groundwater_storage=True,
            accumulation_flux=True,
            persistency_index=True,
            intermittency_monthly=True,
            intermittency_daily=True,
            export_all_tif=False
        )
        
        timeseries_results = BV.postprocessing_timeseries(
            model_modflow=model_modflow,
            model_modpath=None,
            datetime_format=True,
            subbasin_results=True,
            intermittency_monthly=True
        )
        
        # Calculate flow statistics
        simulations_folder = os.path.join(config['out_path'], watershed_name, 'results_simulations')
        simul = os.path.join(simulations_folder, config['model_name'])
        Smod_path = os.path.join(simul, '_postprocess', '_timeseries', '_simulated_timeseries.csv')
        Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
        
        # Temporal configuration
        if config['freq_input'] == 'M':
            temp_config = {'multiplier': 'days_in_period', 'label': 'mm/month'}
        elif config['freq_input'] == 'W':
            temp_config = {'multiplier': 7, 'label': 'mm/week'}
        else:
            temp_config = {'multiplier': 1, 'label': 'mm/day'}
        
        # Prepare observed data
        Qobs_path = os.path.join(config['data_path'], config['study_site'], config['streamflow_obs_file'])
        Qobs = pd.read_csv(Qobs_path, sep=',', index_col=0, parse_dates=True) # ici la colonne zéro est considérée comme index donc elle ne compte pas comme une colonne pour iloc 
        
        if isinstance(Qobs, pd.DataFrame) and Qobs.shape[1] > 1:
            Qobs = Qobs.iloc[:, 0] # donc selectionne la deuxième colonne si on considère que .index est une colonne
        
        Qobs = pd.to_numeric(Qobs, errors='coerce')
        area_m2 = BV.geographic.area * 1e6
        Qobs = (Qobs * 3600 * 24) / area_m2 * 1000 # m3/s to mm/day
        
        # Aggregation according to frequency
        if config['freq_input'] == 'M':
            Qobs = Qobs.resample('M').sum()
        elif config['freq_input'] == 'W':
            Qobs = Qobs.resample('W').sum()
        
        # Prepare modeled flow
        Qmod = Smod['outflow_drain'] * 1000
        if temp_config['multiplier'] == 'days_in_period':
            runoff = BV.climatic.runoff.reindex(Qmod.index)
            Qmod = (Qmod + runoff * 1000) * Qmod.index.day #multiplie par le jour (toujours le dernier) de chaque colonne mois quand freq_input ='M'
        else:
            runoff = BV.climatic.runoff.reindex(Qmod.index)
            Qmod = (Qmod + runoff * 1000) * temp_config['multiplier']
        
        # Data alignment
        mask_obs = (Qobs.index.year >= config['first_year']) & (Qobs.index.year <= config['last_year'])
        mask_mod = (Qmod.index.year >= config['first_year']) & (Qmod.index.year <= config['last_year'])
        Qobs_cal = Qobs[mask_obs]
        Qmod_cal = Qmod[mask_mod]
        
        common_idx = Qobs_cal.index.intersection(Qmod_cal.index)
        Qobs_cal = Qobs_cal.loc[common_idx]
        Qmod_cal = Qmod_cal.loc[common_idx]
        
        # Calculate performance indicators
        try:
            import hydroeval as he
            arr_obs = Qobs_cal.values
            arr_mod = Qmod_cal.values
            NSE = he.evaluator(he.nse, arr_mod, arr_obs)[0]
            NSElog = he.evaluator(he.nse, arr_mod, arr_obs, transform='log')[0]
            KGE = he.evaluator(he.kge, arr_mod, arr_obs)[0][0]
            RMSE = np.sqrt(np.nanmean((arr_obs - arr_mod)**2))
        except ImportError:
            NSE = NSElog = KGE = np.nan
            RMSE = np.sqrt(np.nanmean((arr_obs - arr_mod)**2))
        
        # Initialize default values for spatial metrics
        sim_distance = obs_distance = FA = FQA = np.nan
        
        # Matching streams
        try:
            # Create MatchingStreams object with correct paths
            class MatchingStreams:
                """
                Class for matching simulated and observed stream networks.
                
                Parameters
                ----------
                watershed : object
                    Watershed object
                iteration_label : str, optional
                    Label for this iteration
                from_calib : bool, optional
                    Whether this is from calibration, by default True
                """
                def __init__(self, watershed, iteration_label=None, from_calib=True):
                    self.geographic = watershed.geographic
                    self.hydrography = watershed.hydrography
                    if from_calib == True:
                        self.calibration_folder = watershed.calibration_folder
                    else:
                        # Correct path for simulations
                        self.calibration_folder = os.path.join(
                            config['out_path'], 
                            watershed_name, 
                            'results_simulations'
                        )
                    self.iteration_label = iteration_label
                    
                    self.watershed_shp = watershed.geographic.watershed_shp
                    self.watershed_fill = watershed.geographic.watershed_fill
                    self.watershed_direc = watershed.geographic.watershed_direc
                    
                    try:
                        self.prepare_files()
                        self.sim_to_obs()
                        self.obs_to_sim()
                    except Exception as e:
                        logging.warning(f"MatchingStreams failed: {e}")
                        raise
                
                def prepare_files(self):
                    """Prepare files for matching streams analysis."""
                    # Correct result file paths
                    self.results_folder = os.path.join(self.calibration_folder, self.iteration_label, '_postprocess')
                    os.makedirs(self.results_folder, exist_ok=True)
                    self.dichotomy_folder = os.path.join(self.calibration_folder, self.iteration_label, '_matchingstreams')
                    os.makedirs(self.dichotomy_folder, exist_ok=True)
                    
                    self.buff_tif_obs = self.hydrography.tif_streams
                    self.tif_obs = os.path.join(self.dichotomy_folder, 'obs.tif')
                    toolbox.clip_tif(self.buff_tif_obs, self.watershed_shp, self.tif_obs, False)
                    
                    self.pt_obs = os.path.join(self.dichotomy_folder, 'obs_pt.shp')
                    wbt.raster_to_vector_points(self.tif_obs, self.pt_obs)
                    self.pt_obsf = os.path.join(self.dichotomy_folder, 'obs_ptf.shp')
                    wbt.raster_to_vector_points(self.tif_obs, self.pt_obsf)
                    
                    self.obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.tif')
                    wbt.trace_downslope_flowpaths(self.pt_obs, self.watershed_direc, self.obs_flow)
                    
                    # IMPORTANT CORRECTION: Use correct path for simulation file
                    tif_sim = os.path.join(self.results_folder, '_rasters', 'seepage_areas_t(0).tif')
                    
                    # Check if file exists before continuing
                    if not os.path.exists(tif_sim):
                        # Search in other possible locations
                        alternative_paths = [
                            os.path.join(self.calibration_folder, self.iteration_label, '_postprocess', '_rasters', 'seepage_areas_t(0).tif'),
                            os.path.join(self.calibration_folder, self.iteration_label, 'seepage_areas_t(0).tif'),
                            os.path.join(self.calibration_folder, self.iteration_label, '_rasters', 'seepage_areas_t(0).tif')
                        ]
                        
                        for alt_path in alternative_paths:
                            if os.path.exists(alt_path):
                                tif_sim = alt_path
                                logging.info(f"Found seepage areas file at: {tif_sim}")
                                break
                        else:
                            raise FileNotFoundError(f"Could not find seepage_areas_t(0).tif for {self.iteration_label}")
                    
                    self.tif_sim = os.path.join(self.dichotomy_folder, 'sim.tif')
                    toolbox.clip_tif(tif_sim, self.watershed_shp, self.tif_sim, False)
                    
                    self.pt_sim = os.path.join(self.dichotomy_folder, 'sim_pt.shp')
                    wbt.raster_to_vector_points(self.tif_sim, self.pt_sim)
                    self.pt_simf = os.path.join(self.dichotomy_folder, 'sim_ptf.shp')
                    wbt.raster_to_vector_points(self.tif_sim, self.pt_simf)
                    
                    self.sim_flow = os.path.join(self.dichotomy_folder, 'simflow.tif')
                    wbt.trace_downslope_flowpaths(self.pt_sim, self.watershed_direc, self.sim_flow)
                
                def sim_to_obs(self):
                    """Calculate distances from simulated to observed streams."""
                    self.pt_sim_flow = os.path.join(self.dichotomy_folder, 'simflow.shp')
                    wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flow)
                    self.pt_sim_flowf = os.path.join(self.dichotomy_folder, 'simflowf.shp')
                    wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flowf)
                    
                    self.dist_dem_obs = os.path.join(self.dichotomy_folder, 'dist_dem_obs.tif')
                    wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_obs, self.dist_dem_obs)
                    
                    self.dist_dem_obsflow = os.path.join(self.dichotomy_folder, 'dist_dem_obsflow.tif')
                    wbt.downslope_distance_to_stream(self.watershed_fill, self.obs_flow, self.dist_dem_obsflow)
                    
                    wbt.add_point_coordinates_to_table(self.pt_sim)
                    wbt.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim)
                    wbt.add_point_coordinates_to_table(self.pt_simf)
                    wbt.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_simf)
                    
                    wbt.add_point_coordinates_to_table(self.pt_sim_flow)
                    wbt.extract_raster_values_at_points(self.dist_dem_obs, self.pt_sim_flow)
                    wbt.add_point_coordinates_to_table(self.pt_sim_flowf)
                    wbt.extract_raster_values_at_points(self.dist_dem_obsflow, self.pt_sim_flowf)
                
                def obs_to_sim(self):
                    """Calculate distances from observed to simulated streams."""
                    self.pt_obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.shp')
                    wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flow)
                    self.pt_obs_flowf = os.path.join(self.dichotomy_folder, 'obsflowf.shp')
                    wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flowf)
                    
                    self.dist_dem_sim = os.path.join(self.dichotomy_folder, 'dist_dem_sim.tif')
                    wbt.downslope_distance_to_stream(self.watershed_fill, self.tif_sim, self.dist_dem_sim)
                    self.dist_dem_simflow = os.path.join(self.dichotomy_folder, 'dist_dem_simflow.tif')
                    wbt.downslope_distance_to_stream(self.watershed_fill, self.sim_flow, self.dist_dem_simflow)
                    
                    wbt.add_point_coordinates_to_table(self.pt_obs)
                    wbt.extract_raster_values_at_points(self.dist_dem_sim, self.pt_obs)
                    wbt.add_point_coordinates_to_table(self.pt_obsf)
                    wbt.extract_raster_values_at_points(self.dist_dem_simflow, self.pt_obsf)
                    
                    wbt.add_point_coordinates_to_table(self.pt_obs_flow)
                    wbt.extract_raster_values_at_points(self.dist_dem_sim, self.pt_obs_flow)
                    wbt.add_point_coordinates_to_table(self.pt_obs_flowf)
                    wbt.extract_raster_values_at_points(self.dist_dem_simflow, self.pt_obs_flowf)
            
            ms = MatchingStreams(BV, iteration_label=config['model_name'], from_calib=False)
            
            # Calculate spatial metrics
            # watershed_gdf = gpd.read_file(BV.geographic.watershed_shp)
            # area_km2 = BV.geographic.area
            
            # Check that matching streams files exist
            sim_flowf_path = ms.pt_sim_flowf # équivalent à simf_to_obsf = gpd.read_file(os.path.join(BV.calibration_folder, model_name, '_matchingstreams', 'simflowf.shp'))
            obs_flowf_path = ms.pt_obs_flowf
            
            if not os.path.exists(sim_flowf_path):
                raise FileNotFoundError(f"Simulated flow file not found: {sim_flowf_path}")
            if not os.path.exists(obs_flowf_path):
                raise FileNotFoundError(f"Observed flow file not found: {obs_flowf_path}")
            
            simf_to_obsf = gpd.read_file(sim_flowf_path)
            obsf_to_simf = gpd.read_file(obs_flowf_path)
            
            # Fix the variable reference issue - use the dataframes, not the paths
            mean_simf_to_obsf = np.nanmean(simf_to_obsf[simf_to_obsf['VALUE1'] >= 0]['VALUE1'])
            mean_obsf_to_simf = np.nanmean(obsf_to_simf[obsf_to_simf['VALUE1'] >= 0]['VALUE1'])
            
            sim_distance = mean_simf_to_obsf
            obs_distance = mean_obsf_to_simf
            
            if not np.isnan(sim_distance) and not np.isnan(obs_distance) and obs_distance != 0:
                FA = 1/(1+abs(np.log(sim_distance / obs_distance))) #quand Fa tend vers 1 alors meilleur paramètres
            else:
                FA = np.nan
            
            # Debug logging - CORRECTION: use config instead of worker_config
            worker_id = config.get('worker_id', '?')
            logging.info(f"Worker {worker_id}: Sim river points: {sim_distance}, Obs river points: {obs_distance}")
            
            FQ = NSElog if not np.isnan(NSElog) else np.nan
            FQA = (FQ + FA)/2 if not np.isnan(FQ) and not np.isnan(FA) else np.nan

        except Exception as e:
            logging.warning(f"Matching streams calculation failed: {e}")
            # Variables are already initialized to np.nan above
        
        # Return results
        results = {
            'success': True,
            'hk': hk,
            'sy': sy,
            'NSE': NSE,
            'NSElog': NSElog,
            'KGE': KGE,
            'RMSE': RMSE,
            'sim_distance' : sim_distance,
            'obs_distance' : obs_distance,
            'FA': FA,
            'FQA': FQA,
            'simulation_time': time.time()
        }
        
        return results
        
    except Exception as e:
        logging.error(f"Simulation failed for hk={hk}, sy={sy}: {str(e)}")
        return {
            'success': False,
            'hk': hk,
            'sy': sy,
            'error': str(e)
        }

def worker_function(worker_id, parameters_file, base_config):
    """
    Worker function that processes a parameter file.
    
    Parameters
    ----------
    worker_id : int
        Unique identifier for the worker
    parameters_file : str or Path
        Path to the CSV file containing parameters
    base_config : dict
        Base configuration dictionary
    """
    logger = logging.getLogger()
    logger.info(f"Worker {worker_id} started - Processing {parameters_file}")
    
    try:
        # Configure worker environment
        worker_config = setup_worker_environment(worker_id, base_config)
        
        # Read parameter file
        df_params = pd.read_csv(parameters_file)
        
        # Check that required columns exist
        required_columns = ['hk', 'sy']
        if not all(col in df_params.columns for col in required_columns):
            logger.error(f"Worker {worker_id}: Missing required columns in {parameters_file}")
            return
        
        # Add result columns if they don't exist
        result_columns = ['NSE', 'NSElog', 'KGE', 'RMSE','sim_distance', 'obs_distance', 'FA', 'FQA', 'success', 'error', 'simulation_time']
        for col in result_columns:
            if col not in df_params.columns:
                df_params[col] = np.nan
        
        # Process each row
        for idx, row in df_params.iterrows():
            # Check if this simulation has already been successfully processed
            success_status = row.get('success', np.nan)
            if not pd.isna(success_status) and success_status == True:
                logger.info(f"Worker {worker_id}: Skipping row {idx} (successfully completed)")
                continue
            
            hk = row['hk']
            sy = row['sy']
            iteration_name = f"worker_{worker_id}_iter_{idx}"
            
            logger.info(f"Worker {worker_id}: Processing row {idx} - hk={hk}, sy={sy}")
            
            # Launch simulation
            start_time = time.time()
            results = run_single_simulation(hk, sy, worker_config, iteration_name)
            end_time = time.time()
            
            # Save results
            for key, value in results.items():
                if key in df_params.columns:
                    df_params.at[idx, key] = value
            
            df_params.at[idx, 'simulation_time'] = end_time - start_time
            
            # Save file after each simulation
            df_params.to_csv(parameters_file, index=False)
            
            if results['success']:
                logger.info(f"Worker {worker_id}: Row {idx} completed successfully")
            else:
                logger.error(f"Worker {worker_id}: Row {idx} failed - {results.get('error', 'Unknown error')}")
            
            # Clean temporary files for this simulation
            try:
                simulation_dir = os.path.join(worker_config['out_path'])
                if os.path.exists(simulation_dir):
                    shutil.rmtree(simulation_dir)
                logger.info(f"Worker {worker_id}: Cleaned temporary files for row {idx}")
            except Exception as e:
                logger.warning(f"Worker {worker_id}: Failed to clean temporary files: {e}")
        
        logger.info(f"Worker {worker_id}: Completed processing {parameters_file}")
        
    except Exception as e:
        logger.error(f"Worker {worker_id}: Fatal error - {str(e)}")
    
    finally:
        # Clean worker temporary directory
        try:
            worker_temp_dir = os.path.join(base_config['temp_base_dir'], f'worker_{worker_id}')
            if os.path.exists(worker_temp_dir):
                shutil.rmtree(worker_temp_dir)
            logger.info(f"Worker {worker_id}: Cleaned worker temporary directory")
        except Exception as e:
            logger.warning(f"Worker {worker_id}: Failed to clean worker directory: {e}")

def main():
    """
    Main function to launch parallelized calibration.
    
    The function sets up the base configuration, finds parameter files,
    and launches multiple worker processes to perform calibration simulations
    in parallel.
    """
    # Base configuration (ADAPT THESE PATHS TO YOUR CONFIGURATION)
    base_config = {
        # Paths - ADAPT THESE PATHS TO YOUR CONFIGURATION
        'root_dir': r'C:\Users\theat\Documents\Python\01_Git_Repository\01-HMPdev-sewage',  # Your root_dir
        'out_path': r'C:\Users\theat\Documents\Python\02_Output_HydroModPy',  # Your out_path
        'data_path': r'C:\Users\theat\Documents\Python\02_Output_HydroModPy\data',  # Your data_path
        'dem_path': r'C:\Users\theat\Documents\Python\02_Output_HydroModPy\data\regional dem.tif',  # Your dem_path
        'temp_base_dir': r'C:\Users\theat\Documents\Python\tmp\hydromod_calibration',  # Base temporary directory
        
        # Study parameters
        'study_site': 'NANCON',
        'first_year': 2000,
        'last_year': 2010,
        'freq_input': 'M',
        'sim_state': 'transient',
        
        # Streamflow observations file
        'streamflow_obs_file': 'J001401001.csv',  # streamflow observations file
        
        # Fixed hydraulic parameters
        'thick': 30,
        'nlay': 1,
        'lay_decay': 1,
        'bottom': None,
        'cond_drain': None,
        
        # Modeling parameters
        'from_xyv': [389358,6816630, 150, 10, 'EPSG:2154'],
        'load': True,
        'save_object': True,
        'box': True,
        'sink_fill': False,
        'plot_cross': False,
        'dis_perlen': True,
        'bc_left': None,
        'bc_right': None,
        'sea_level': 'None',
        
        # Computation parameters
        'n_cores': 8
    }
    
    # Create base temporary directory
    os.makedirs(base_config['temp_base_dir'], exist_ok=True)
    
    # Find parameter files
    parameters_folder = Path(base_config['root_dir']) / 'users' / 'thea' / 'parameters'
    print(f"Looking for parameter files in {parameters_folder}")
    parameter_files = list(parameters_folder.glob('parameters_*.csv'))
    
    if not parameter_files:
        logging.error("No parameter files found!")
        return
    
    logging.info(f"Found {len(parameter_files)} parameter files")
    
    # Limit number of files to available cores
    parameter_files = parameter_files[:base_config['n_cores']]
    
    # Create processes
    processes = []
    for i, param_file in enumerate(parameter_files):
        worker_id = i + 1
        p = mp.Process(
            target=worker_function,
            args=(worker_id, param_file, base_config)
        )
        processes.append(p)
        p.start()
        logging.info(f"Started worker {worker_id} for file {param_file}")
    
    # Wait for all processes to complete
    for p in processes:
        p.join()
    
    logging.info("All workers completed!")
    
    # Clean main temporary directory
    try:
        shutil.rmtree(base_config['temp_base_dir'])
        logging.info("Cleaned main temporary directory")
    except Exception as e:
        logging.warning(f"Failed to clean main temporary directory: {e}")

if __name__ == "__main__":
    main()