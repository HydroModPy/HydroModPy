# -*- coding: utf-8 -*-
"""
COMPLETE MODELING WORKFLOW - Generic Pipeline
Enchaîne: MODFLOW → MODPATH → MT3DMS
3 fonctions séparées: complete_modflow(), complete_modpath(), complete_mt3dms()
"""

import os
import glob
import numpy as np
import whitebox
from itertools import islice
from pathlib import Path
import pickle
import hydromodpy as hmp
# HYDROMODPY MODULES
import hydromodpy as hmp
from hydromodpy import watershed_root
from hydromodpy.watershed import Geographic, Workspace, Climatic, Driasclimat, Driaseau, \
    Hydrography, Intermittency, Piezometry, Settings, \
    SafranSurfex, Subbasin
from hydromodpy.data_managers.hydrometry.station_set import StationSet
from hydromodpy.data_managers.oceanic import Oceanic
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.display import visualization_watershed, visualization_results, export_vtuvtk
from hydromodpy.tools import toolbox
from hydromodpy.domain import (
    Domain,
)
from hydromodpy.data_managers import DataManagers
from hydromodpy.data_managers.geology.geology_field import GeologyField
from hydromodpy.process import Flow, Transport
from hydromodpy.process.flow.sinks_sources import FlowRechargeConfig
from hydromodpy.solver import modflow_nwt, modflow6
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
from hydromodpy.modeling import timeseries, netcdf
from hydromodpy.calibration.calibration_legacy.matching_stream import MatchingStreams
wbt = whitebox.WhiteboxTools()
wbt.verbose = False


# ============================================================================
# COMPLETE MODFLOW - Enchaîne: preprocessing → processing → postprocessing
# ============================================================================

def complete_modflow(geographic, flow, domain, settings, climatic, oceanic_object,
                    model_name, bin_path, workspace, config, cfg, params):
    try:
        # 1. Utilisation de "first_clim" depuis le dictionnaire PARAMS du launcher
        first_clim_val = params.get("first_clim", "mean")

        # Injection dans le flux (Règle ton erreur AttributeError)
        flow.set_recharge(FlowRechargeConfig(
            values=climatic.recharge,
            first_clim=first_clim_val,
        ))

        # 2. Préparation des options avec les valeurs de PARAMS
        preprocess_options = ModflowPreprocessOptions(
            box=params.get("box", True),           # Tiré de PARAMS
            sink_fill=params.get("sink_fill", False), # Tiré de PARAMS
            check_grid=params.get("check_grid", True), # Tiré de PARAMS
            plot_cross=params.get("plot_cross", True), # Tiré de PARAMS
            cross_ylim=tuple(params.get("cross_ylim", [0, 150])), # Tiré de PARAMS
        )

        # 3. Choix du moteur (via cfg/TOML)
        solver_engine = cfg.solver.solver_engine
        model_folder=workspace.simulations_folder
        # Instanciation (NWT ou MF6)
        if solver_engine == SolverEngine.MODFLOW_NWT:
            model_modflow = Modflow(
                geographic,
                model_folder=workspace.simulations_folder,
                model_name=model_name,
                bin_path=bin_path,
                modflow_config=cfg.modflownwt,
                preprocess_options=preprocess_options,
            )
        else:
            from hydromodpy.solver.modflow6 import Modflow6
            model_modflow = Modflow6(
                geographic,
                model_folder=workspace.simulations_folder,
                model_name=model_name,
                bin_path=bin_path,
                modflow_config=cfg.modflow6,
                preprocess_options=preprocess_options,
            )

        # 4. Exécution
        model_modflow.pre_processing(flow=flow, domain=domain, options=preprocess_options)

        # 5. Sauvegarde Pickle (Important pour le rechargement)
        save_dir = os.path.join(model_folder, model_name)
        os.makedirs(save_dir, exist_ok=True)
        with open(os.path.join(save_dir, f'results_{model_name}.pkl'), 'wb') as f:
            pickle.dump({'list_model_name': [model_name], 'list_model_modflow': [model_modflow]}, f)

        # 6. Processing
        success = model_modflow.processing(
            options=ModflowRunOptions(write_model=True, run_model=True, link_mt3dms=True)
        )

        # 7. Post-processing
        if success:
            model_modflow.post_processing(
                options=ModflowPostprocessOptions(
                    watertable_elevation=True,
                    seepage_areas=True,
                    outflow_drain=True,
                    watertable_depth=True,
                    intermittency_monthly=True
                )
            )

        return {'model_modflow': model_modflow, 'success': success, 'model_name': model_name}

    except Exception as e:
        print(f"MODFLOW Error: {e}")
        import traceback
        traceback.print_exc()
        return {'model_modflow': None, 'success': False, 'model_name': model_name}
# ============================================================================
# COMPLETE MODPATH - Enchaîne: preprocessing → processing → postprocessing → filtering
# ============================================================================

def complete_modpath(domain, transport, solver_engine, workspace, vers,
                     model_modpath=None):
    """
    Complete MODPATH workflow: Pre-processing → Processing → Post-processing → Filtering

    Enchaîne directement les étapes: preprocessing, processing, postprocessing, filt_processing

    Parameters
    ----------
    geographic : Geographic object
    settings : Settings object
    model_modflow : Modflow object
    initializing : Initializing object
    model_name : str
        Model identification name
    for_calib : bool, default False
        Calibration mode
    config : dict, optional
        Configuration with 'preprocessing', 'processing', 'post_processing', 'filt_processing' keys

    Returns
    -------
    dict
        Result dictionary with keys: model_modpath, success
    """
    print(f"\n{'='*70}")
    print(f"MODPATH WORKFLOW")
    print(f"{'='*70}")

    if solver_engine != SolverEngine.MODFLOW_NWT:
        print("MODPATH workflow is currently available only with solver_engine='nwt'. Skipping section B.")
        return {'model_modpath': None, 'success': False}
    else:
        # 1. Trouver le dossier et charger le pickle
        list_folder = glob.glob(os.path.join(str(workspace.simulations_folder), vers+'*'))
        model_name = list_folder[0].split(os.path.sep)[-1]
        pickle_file = list_folder[0] + '/' + 'results_' + model_name + '.pkl'

        with open(pickle_file, 'rb') as f:
            d = pickle.load(f)
        model_modflow = d['list_model_modflow'][0]

        # 2. Whitebox : Préparation des particules
        tif_seep = os.path.join(workspace.simulations_folder, model_name, '_postprocess/_rasters','seepage_areas_t(0).tif')
        tif_seep_clip = os.path.join(workspace.simulations_folder, model_name, '_postprocess/_rasters','seepage_areas_t(0)_clip.tif')

        wbt.clip_raster_to_polygon(
            tif_seep,
            os.path.join(workspace.stable_folder, 'geographic', 'watershed.shp'),
            tif_seep_clip,
            maintain_dimensions=True)

        # 3. Paramètres transport
        _params_obj = transport.particle.parameters
        particle_params = _params_obj if isinstance(_params_obj, dict) else _params_obj.model_dump()
        if particle_params.get('zone_partic') == 'seepage_clip':
            particle_params['zone_partic'] = tif_seep_clip
        transport.particle.set_parameters(particle_params)

        # 4. Instance et exécution
        model_modpath = Modpath(domain,
                        transport,
                        model_modflow,
                        model_folder = workspace.simulations_folder,
                        model_name = model_modflow.model_name,
                        bin_path = workspace.bin_path)

        model_modpath.pre_processing()
        success = model_modpath.processing(write_model=True, run_model=True)

        if success:
            model_modpath.post_processing(model_modpath,
                        ending_point=True, starting_point=True,
                        pathlines_shp=True, particles_shp=True, random_id=None)

            model_modpath.filt_processing(model_modpath,
                        norm_flux=True, filt_time=True, filt_seep=True,
                        filt_inout=True, calc_rtd=False, random_id=None)

        return {'model_modpath': model_modpath, 'success': success}

# ============================================================================
# COMPLETE MT3DMS - Enchaîne: preprocessing → processing → postprocessing
# ============================================================================

def complete_mt3dms(geographic, climatic, model_modflow,domain, workspace,transport, solver_engine,vers,
                   scenario='s1'):
    """
    Complete MT3DMS workflow: Pre-processing → Processing → Post-processing

    Enchaîne directement les 3 étapes: preprocessing, processing, postprocessing

    Parameters
    ----------
    geographic : Geographic object
    climatic : Climatic object
    model_modflow : Modflow object
    initializing : Initializing object
    model_name : str
        Model identification name
    scenario : str, default 's1'
        Scenario identifier
    for_calib : bool, default False
        Calibration mode
    transport : Transport object, optional
        Transport parameters
    config : dict, optional
        Configuration with 'preprocessing', 'processing', 'post_processing' keys

    Returns
    -------
    dict
        Result dictionary with keys: model_mt3dms, success
    """
    print(f"\n{'='*70}")
    print(f"{'='*70}")

    if not model_modflow:
        print("✗ MT3DMS skipped (MODFLOW not available)\n")
        return {'model_mt3dms': None, 'success': False}

    list_folder = glob.glob(os.path.join(str(workspace.simulations_folder), vers+'*'))
    model_name = list_folder[0].split(os.path.sep)[-1]
    print(f"MT3DMS WORKFLOW: {model_name} - scenario '{scenario}'")
    pickle_file = list_folder[0] + '/' + 'results_' + model_name + '.pkl'

    with open(pickle_file, 'rb') as f:
        d = pickle.load(f)
    model_modflow = d['list_model_modflow'][0]

    model_mt3dms = None
    nper = model_modflow.nper

    # 2. Détection des dimensions
    if solver_engine == SolverEngine.MODFLOW_NWT:
        nlay = model_modflow.mf.nlay
        nrow = model_modflow.mf.nrow
        ncol = model_modflow.mf.ncol
    else:
        nlay = model_modflow.nlay
        nrow = model_modflow.nrow
        ncol = model_modflow.ncol

    # 3. Tableaux de concentration
    sconc_init = np.ones((nlay, nrow, ncol)) * (100/1000)
    sconc_input = {i: np.ones((nrow, ncol)) * (50/1000) for i in range(nper)}
    sconc_input = dict(islice(sconc_input.items(), 1, None))
    rate_decay = np.ones((nlay, nrow, ncol)) * (1/(2*365))

    transport.conc.set_parameters(spc_name='NO3',
                                  sconc_init=sconc_init,
                                  sconc_input=sconc_input,
                                  rate_decay=rate_decay)

    # 4. Exécution du Transport
    scenario = 's1'
    suffix_name = '_mt_'+scenario

    if solver_engine == SolverEngine.MODFLOW_NWT:
        model_mt3dms = Mt3dms(domain, transport, model_modflow,
                            model_folder = workspace.simulations_folder,
                            model_name = model_modflow.model_name,
                            suffix_name = suffix_name,
                            bin_path = workspace.bin_path)
    else:
        model_mt3dms = Modflow6Transport(domain, transport, model_modflow,
                            model_folder = workspace.simulations_folder,
                            model_name = model_modflow.model_name,
                            suffix_name = suffix_name,
                            bin_path = workspace.bin_path)

    model_mt3dms.pre_processing()
    success_mt3dms = model_mt3dms.processing(write_model=True, run_model=True, verbose=True)

    # 5. Post-processing et Timeseries
    if success_mt3dms:
        # NWT vs MF6 pour mass_accumulated
        mass_acc = True if solver_engine == SolverEngine.MODFLOW_NWT else False

        model_mt3dms.post_processing(model_mt3dms,
                                concentration_seepage=True,
                                mass_seepage=True,
                                mass_accumulated=mass_acc,
                                export_all_tif=True)

        timeseries_results = timeseries.Timeseries(geographic,
                                                    model_modflow=model_modflow,
                                                    runoff=climatic.runoff,
                                                    model_modpath=None, # Sera mis à jour par le launcher si besoin
                                                    model_mt3dms=model_mt3dms,
                                                    suffix_name=scenario,
                                                    datetime_format=True,
                                                    subbasin_results=True,
                                                    intermittency_weekly=False,
                                                    intermittency_monthly = True,
                                                    residence_times=True,
                                                    concentration_seepage=True,
                                                    mass_accumulated=mass_acc)

        return {'model_mt3dms': model_mt3dms, 'success': True, 'timeseries': timeseries_results}
    else:
        return {'model_mt3dms': None, 'success': False}
# ============================================================================
# COMPLETE TIMESERIES - Generate timeseries results (postprocessing)
# ============================================================================

def complete_timeseries(geographic, model_modflow, runoff=None, model_modpath=None, model_mt3dms=None,
                       scenario='s1', config=None):
    """
    Complete TIMESERIES workflow: Generate timeseries results

    Parameters
    ----------
    geographic : Geographic object
    model_modflow : Modflow object
    model_modpath : Modpath object, optional
    model_mt3dms : Mt3dms object, optional
    scenario : str, default 's1'
        Scenario identifier
    config : dict, optional
        Configuration (reserved for future use)

    Returns
    -------
    dict
        Result dictionary with keys: timeseries_results, success
    """
    print(f"\n{'='*70}")
    print(f"TIMESERIES WORKFLOW: {scenario}")
    print(f"{'='*70}")

    if not model_modflow:
        print("TIMESERIES skipped (MODFLOW not available)\n")
        return {'timeseries_results': None, 'success': False}

    try:
        print("Creating Timeseries object...")

        # Create Timeseries instance (like example12.py line 856)
        # suffix_name only when MT3DMS is present, otherwise None for generic _simulated_timeseries.csv
        suffix_name = scenario if model_mt3dms is not None else None
        timeseries_results = timeseries.Timeseries(
            geographic,
            model_modflow=model_modflow,
            runoff=runoff,
            model_modpath=model_modpath,
            model_mt3dms=model_mt3dms,
            suffix_name=suffix_name,
            datetime_format=True,
            subbasin_results=True,
            intermittency_weekly=False,
            intermittency_monthly=True,
            residence_times=(model_modpath is not None),
            concentration_seepage=(model_mt3dms is not None),
            mass_accumulated=(model_mt3dms is not None)
        )

        print("TIMESERIES completed\n")
        return {'timeseries_results': timeseries_results, 'success': True}

    except Exception as e:
        import traceback
        print(f"TIMESERIES error: {e}")
        traceback.print_exc()
        return {'timeseries_results': None, 'success': False}
