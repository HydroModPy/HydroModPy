#%%
# # -*- coding: utf-8 -*-
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

def run_single_simulation(hk,hk_decay, exdp, sy, sy_decay, ss, ss_decay, alpha, worker_config, iteration_name):
    """
    Run a single simulation with given parameters.
    
    Parameters
    ----------
    exdp : float
        Extinction depth for evapotranspiration (m)
    sy : float
        Specific yield parameter  
    base_config : dict
        Base configuration dictionary
    iteration_name : str
        Name for this iteration
    #!! FAIRE LA DOCSTRING COMPLETE AVEC TOUS LES PARAMETRES
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
        root_dir = worker_config['root_dir']
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
        config = worker_config.copy()
        config['hk'] = hk
        config['hk_decay'] = hk_decay
        config['exdp'] = exdp
        config['sy'] = sy
        config['sy_decay'] = sy_decay
        config['ss'] = ss
        config['ss_decay'] = ss_decay
        config['alpha'] = alpha
        config['model_name'] = iteration_name
        
        # Ensure worker_id is available for logs
        worker_id = config.get('worker_id', 'unknown')
        logging.info(f"Worker {worker_id}: Starting simulation hk={hk}, exdp={exdp}, sy={sy}, alpha={alpha}")
        
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
        # BV.add_geology(config['data_path'], types_obs='GEO1M.shp', fields_obs='CODE_LEG')
        BV.add_hydrography(
            os.path.join(config['data_path'], 'hydrography'),
            types_obs=['COURS_D_EAU']
        )
        # BV.add_hydrometry(
            # os.path.join(config['data_path'], 'hydrometry'), 
            # 'france hydrometric stations.shp')
        
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
            'recharge': 'mean', 'runoff': 'mean', 'precip': 'mean',
            'evt': 'mean', 'etp': 'mean', 't': 'mean'
        }
        df_climatic = df_climatic.resample(config['freq_input']).agg(agg_dict)
        
        # Climatic configuration
        BV.climatic.runoff = df_climatic['runoff']
        BV.climatic.precip = df_climatic['precip']
        BV.climatic.evt = df_climatic['evt']
        BV.climatic.etp = df_climatic['etp']
        BV.climatic.t = df_climatic['t']
        BV.climatic.recharge = BV.climatic.precip - BV.climatic.etp - BV.climatic.runoff
        
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
        
        # Hydraulic parameters (uses hk fixed and sy variable)
        BV.hydraulic.update_nlay(config['nlay'])
        BV.hydraulic.update_lay_decay(config['lay_decay'])
        BV.hydraulic.update_bottom(config['bottom'])
        BV.hydraulic.update_thick(config['thick'])
        
        BV.hydraulic.update_hk(config['hk'] * 3600 * 24)  # Fixed parameter from configr       
        BV.hydraulic.update_hk_decay(hk_decay_value=config['hk_decay'][0],
                                     min_value=config['hk_decay'][1], 
                                     log_transf=config['hk_decay'][2], 
                                     grad_elev=config['hk_decay'][3])
        
        BV.hydraulic.update_ss(ss)  # Variable parameter
        BV.hydraulic.update_ss_decay(ss_decay_value=config['ss_decay'][0],
                                     min_value=config['ss_decay'][1], 
                                     log_transf=config['ss_decay'][2], 
                                     grad_elev=config['ss_decay'][3])
        
        BV.hydraulic.update_sy(sy / 100)  # Variable parameter
        BV.hydraulic.update_sy_decay(sy_decay_value=config['sy_decay'][0],
                                     min_value=config['sy_decay'][1], 
                                     log_transf=config['sy_decay'][2], 
                                     grad_elev=config['sy_decay'][3])

        BV.hydraulic.update_cond_drain(config['cond_drain'])
        BV.hydraulic.update_exdp(exdp)  # Variable parameter for extinction depth

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
                'hk': hk,
                'exdp': exdp,
                'sy': sy,
                'alpha': alpha,
                'error': 'MODFLOW simulation failed',
                'simulation_time': None
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
        
        # # cas de NAIZIN Prepare observed data
        # Qobs_path = os.path.join(config['data_path'], config['study_site'], config['streamflow_obs_file'])
        # Qobs = pd.read_csv(Qobs_path, sep=';', index_col=0, parse_dates=True)  # Parse dates from the first column
        # Qobs.index = pd.to_datetime(Qobs.index, format='%d/%m/%Y')  # Ensure the date format is correctly interpreted
        # Qobs = Qobs['Q_Lperday']  # Select the column with flow data
        # Qobs = pd.to_numeric(Qobs, errors='coerce')  # Convert to numeric, coercing errors to NaN
        # area_m2 = BV.geographic.area * 1e6  # Convert area from km² to m²
        # Qobs = Qobs / 1000  # Convert flow from L/day to m³/day
        # Qobs = Qobs / area_m2 * 1000  # Convert m³/day to mm/day
        
        # Prepare observed data - IMPROVED CSV READING
        Qobs_path = os.path.join(config['data_path'], config['study_site'], "hydrometry", config['streamflow_obs_file'])
        
        def read_hydrometric_csv_robust(file_path):
            """
            Robust function to read hydrometric CSV files with different formats.
            
            Parameters
            ----------
            file_path : str
                Path to the CSV file
                
            Returns
            -------
            pd.Series
                Time series of flow data
            """
            # Try different separators and encoding
            separators = [',', ';', '\t']
            encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
            
            for sep in separators:
                for encoding in encodings:
                    try:
                        # First, read without parsing dates to examine structure
                        df_test = pd.read_csv(file_path, sep=sep, encoding=encoding, nrows=5)
                        
                        # Check if we have at least 2 columns (date + flow)
                        if df_test.shape[1] < 2:
                            continue
                            
                        # Now read with proper settings
                        df = pd.read_csv(file_path, sep=sep, encoding=encoding)
                        
                        # Identify date and flow columns
                        # Look for common date column names/patterns
                        date_col = None
                        flow_col = None
                        
                        # Common date column indicators
                        date_indicators = ['date', 'time', 'Date', 'DATE', 'Time', 'TIME', 'datetime', 'DATETIME']
                        flow_indicators = ['q', 'Q', 'flow', 'Flow', 'FLOW', 'debit', 'Debit', 'DEBIT']
                        
                        # Find date column
                        for col in df.columns:
                            col_str = str(col).lower()
                            if any(indicator.lower() in col_str for indicator in date_indicators):
                                date_col = col
                                break
                        
                        # If no explicit date column found, assume first column is date
                        if date_col is None:
                            date_col = df.columns[0]
                        
                        # Find flow column
                        for col in df.columns:
                            if col != date_col:
                                col_str = str(col).lower()
                                if any(indicator.lower() in col_str for indicator in flow_indicators):
                                    flow_col = col
                                    break
                        
                        # If no explicit flow column found, assume second column or first non-date column
                        if flow_col is None:
                            remaining_cols = [col for col in df.columns if col != date_col]
                            if remaining_cols:
                                flow_col = remaining_cols[0]
                            else:
                                continue
                        
                        # Extract data
                        flow_data = df[flow_col]
                        date_data = df[date_col]
                        
                        # Convert dates - try different formats
                        date_formats = ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d', 
                                       '%d-%m-%Y', '%m-%d-%Y', '%d.%m.%Y', '%Y.%m.%d']
                        
                        parsed_dates = None
                        for date_format in date_formats:
                            try:
                                parsed_dates = pd.to_datetime(date_data, format=date_format)
                                break
                            except:
                                continue
                        
                        # If specific formats fail, use pandas' automatic parsing
                        if parsed_dates is None:
                            try:
                                parsed_dates = pd.to_datetime(date_data, infer_datetime_format=True)
                            except:
                                continue
                        
                        # Convert flow to numeric
                        flow_numeric = pd.to_numeric(flow_data, errors='coerce')
                        
                        # Create series with date index
                        flow_series = pd.Series(flow_numeric.values, index=parsed_dates)
                        
                        # Remove NaN values
                        flow_series = flow_series.dropna()
                        
                        # Check if we have valid data
                        if len(flow_series) > 0:
                            logging.info(f"Successfully read CSV with separator '{sep}' and encoding '{encoding}'")
                            logging.info(f"Found {len(flow_series)} valid flow observations")
                            logging.info(f"Date range: {flow_series.index.min()} to {flow_series.index.max()}")
                            return flow_series
                            
                    except Exception as e:
                        logging.debug(f"Failed with sep='{sep}', encoding='{encoding}': {e}")
                        continue
            
            # If all attempts failed, raise an error
            raise ValueError(f"Could not read CSV file {file_path}. Tried multiple separators and encodings.")
        
        try:
            Qobs = read_hydrometric_csv_robust(Qobs_path)
            logging.info(f"Successfully loaded hydrometric data from {Qobs_path}")
        except Exception as e:
            logging.error(f"Failed to read hydrometric CSV: {e}")
            raise
        
        # Convert units: assume input is in m³/s, convert to mm/day
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
            'hk' : hk,
            'exdp': exdp,
            'sy': sy,
            'alpha': alpha,
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
        logging.error(f"Simulation failed for hk={hk}, exdp={exdp}, sy={sy}, alpha={alpha}: {str(e)}")
        return {
            'success': False,
            'hk': hk,
            'exdp': exdp,
            'sy': sy,
            'alpha': alpha,
            'error': str(e),
            'simulation_time': None
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
        required_columns = ['exdp', 'sy']
        if not all(col in df_params.columns for col in required_columns):
            logger.error(f"Worker {worker_id}: Missing required columns in {parameters_file}")
            return
        
        # Add result columns if they don't exist
        result_columns = ['hk', 'NSE', 'NSElog', 'KGE', 'RMSE','sim_distance', 'obs_distance', 'FA', 'FQA', 'success', 'error', 'simulation_time']
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
            
            # Use fixed hk, hk_decay and sy_decay from base_config
            hk = base_config['hk']
            hk_decay = base_config['hk_decay']
            exdp = row['exdp']
            sy = row['sy']
            sy_decay = base_config['sy_decay']
            ss = base_config['ss']
            ss_decay = base_config['ss_decay']
            alpha = base_config['alpha']

            iteration_name = f"worker_{worker_id}_iter_{idx}"

            logger.info(f"Worker {worker_id}: Processing row {idx} - hk={hk} (fixed), exdp={exdp}, sy={sy}")

            # Launch simulation
            start_time = time.time()
            results = run_single_simulation(hk, hk_decay, exdp, sy, sy_decay, ss, ss_decay, alpha, worker_config, iteration_name)
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
        
        logger.info(f"Worker {worker_id}: Completed processing {parameters_file}")
        
    except Exception as e:
        logger.error(f"Worker {worker_id}: Fatal error - {str(e)}")
    
    finally:
        # Clean worker temporary directory with retry logic for Windows file locks
        try:
            worker_temp_dir = os.path.join(base_config['temp_base_dir'], f'worker_{worker_id}')
            if os.path.exists(worker_temp_dir):
                # Retry logic for Windows file locks
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        shutil.rmtree(worker_temp_dir)
                        logger.info(f"Worker {worker_id}: Cleaned worker temporary directory")
                        break
                    except (PermissionError, OSError) as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"Worker {worker_id}: Failed to clean directory (attempt {attempt + 1}/{max_retries}), retrying in 2 seconds...")
                            time.sleep(2)
                        else:
                            logger.warning(f"Worker {worker_id}: Failed to clean worker directory after {max_retries} attempts: {e}")
                            raise
        except Exception as e:
            logger.warning(f"Worker {worker_id}: Failed to clean worker directory: {e}")

# Use multiprocessing Pool for parallel processing
def worker_wrapper(args):
    return worker_function(*args)
def test_csv_reading(config):
    """
    Test function to validate CSV file reading before running simulations.
    
    Parameters
    ----------
    config : dict
        Base configuration dictionary
        
    Returns
    -------
    bool
        True if CSV can be read successfully, False otherwise
    """
    try:
        # Test hydrometric CSV reading
        Qobs_path = os.path.join(config['data_path'], config['study_site'], "hydrometry", config['streamflow_obs_file'])
        
        if not os.path.exists(Qobs_path):
            logging.error(f"Hydrometric file not found: {Qobs_path}")
            return False
            
        logging.info(f"Testing CSV reading for: {Qobs_path}")
        
        # Try to read with different separators
        separators = [',', ';', '\t']
        encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
        
        success = False
        for sep in separators:
            for encoding in encodings:
                try:
                    df = pd.read_csv(Qobs_path, sep=sep, encoding=encoding, nrows=10)
                    logging.info(f"✓ Successfully read with separator '{sep}' and encoding '{encoding}'")
                    logging.info(f"  Columns: {list(df.columns)}")
                    logging.info(f"  Shape: {df.shape}")
                    logging.info(f"  First few rows:")
                    for i, row in df.head(3).iterrows():
                        logging.info(f"    {dict(row)}")
                    success = True
                    break
                except Exception as e:
                    logging.debug(f"  Failed with sep='{sep}', encoding='{encoding}': {e}")
            if success:
                break
                
        if not success:
            logging.error("Could not read CSV file with any separator/encoding combination")
            return False
            
        # Test climatic CSV reading
        climatic_path = os.path.join(config['data_path'], config['study_site'], 'Meteo', 'Historiques SIM2', 'climatic_data.csv')
        if os.path.exists(climatic_path):
            try:
                df_climatic = pd.read_csv(climatic_path, index_col=0, parse_dates=True, nrows=5)
                logging.info(f"✓ Climatic CSV readable: {climatic_path}")
                logging.info(f"  Columns: {list(df_climatic.columns)}")
            except Exception as e:
                logging.warning(f"⚠ Climatic CSV might have issues: {e}")
        else:
            logging.warning(f"⚠ Climatic CSV not found: {climatic_path}")
            
        return True
        
    except Exception as e:
        logging.error(f"CSV testing failed: {e}")
        return False

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
        'dem_path': r'C:\Users\theat\Documents\Python\02_Output_HydroModPy\data\dem\Naizin25m.tif',  # Your dem_path
        'temp_base_dir': r'C:\Users\theat\Documents\Python\tmp\hydromod_calibration',  # Base temporary directory
        
        # Study 
        'study_site': 'KERVIDY_NAIZIN',
        'first_year': 2021,
        'last_year': 2021,
        'freq_input': 'M',
        'sim_state': 'transient',
        
        # Streamflow observations file
        'streamflow_obs_file': 'J560681001.csv',  # streamflow observations file
        
        # Fixed hydraulic parameters
        'hk': 5e-5,  # Fixed hydraulic conductivity (m/s) - ADJUST THIS VALUE AS NEEDED
        'thick': None,
        'nlay': 20,
        'lay_decay': 1,
        'bottom': 0,
        'cond_drain': None,
        'ss': 1e-5,  # Specific storage top of the layer (m^-1)
        'alpha': (1/21),
        'hk_decay': ((1/21), None, True, []),  # Example fixed values
        'sy_decay': (((1/21)/2), None, True, []),  # Example fixed values,
        'ss_decay': (((1/21)/2), None, True, []),  # Example fixed values
        # Modeling parameters
        'from_xyv': [265547, 6783313, 150, 10, 'EPSG:2154'],
        'load': False,
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
        
    # Test CSV file reading before proceeding
    logging.info("Testing CSV file reading...")
    if not test_csv_reading(base_config):
        logging.error("CSV reading test failed. Please check your data files and formats.")
        return
    logging.info("✓ CSV reading test passed!")
    
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

    # Prepare arguments for each worker
    worker_args = [
        (i + 1, param_file, base_config)
        for i, param_file in enumerate(parameter_files)
    ]

    # Create a pool of workers
    with mp.Pool(processes=base_config['n_cores']) as pool:
        pool.map(worker_wrapper, worker_args,chunksize=1)
        
    # # Create processes
    # processes = []
    # for i, param_file in enumerate(parameter_files):
    #     worker_id = i + 1
    #     p = mp.Process(
    #         target=worker_function,
    #         args=(worker_id, param_file, base_config)
    #     )
    #     processes.append(p)
    #     p.start()
    #     logging.info(f"Started worker {worker_id} for file {param_file}")
    
    ## Wait for all processes to complete
    # for p in processes:
    #     p.join()
    
    logging.info("All workers completed!")
    
    # Clean main temporary directory
    try:
        shutil.rmtree(base_config['temp_base_dir'])
        logging.info("Cleaned main temporary directory")
    except Exception as e:
        logging.warning(f"Failed to clean main temporary directory: {e}")
        
if __name__ == "__main__":
    main()