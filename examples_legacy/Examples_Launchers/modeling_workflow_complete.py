# -*- coding: utf-8 -*-
"""
COMPLETE MODELING WORKFLOW - Generic Pipeline
EnchaÃ®ne: MODFLOW â†’ MODPATH â†’ MT3DMS
3 fonctions sÃ©parÃ©es: complete_modflow(), complete_modpath(), complete_mt3dms()
"""

import os
import glob
import numpy as np
import whitebox
from itertools import islice
from pathlib import Path
import pickle
import hydromodpy as hmp
# Direct class imports (like example12.py)
from hydromodpy.solver.modflow import Modflow
from hydromodpy.solver.modflow_nwt import Modpath
from hydromodpy.solver.modflow_nwt import Mt3dms
from hydromodpy.postprocess import netcdf
from hydromodpy.postprocess import timeseries
from hydromodpy.postprocess.flow.matching_streams import MatchingStreams
# HYDROMODPY MODULES
import hydromodpy as hmp
from hydromodpy import watershed_root_legacy
from hydromodpy.geographic import Geographic, Subbasin
from hydromodpy.data_managers.climatic import Climatic
from hydromodpy.legacy.watershed import Driasclimat, Driaseau, \
    Hydraulic, Hydrography, Hydrometry, Piezometry, Settings, \
    SafranSurfex, Transport
from hydromodpy.data_managers.variables.oceanic import OceanicManager, OceanicConfig, OceanicSourceConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.display import visualization_watershed, visualization_results, export_vtuvtk
from hydromodpy.support.tools import toolbox
from hydromodpy.process import Flow
from hydromodpy.solver.modflow import Modflow
from hydromodpy.solver.modflow_nwt import Modpath
from hydromodpy.solver.modflow_nwt import Mt3dms
from hydromodpy.postprocess import netcdf
from hydromodpy.postprocess import timeseries
from hydromodpy.postprocess.flow.matching_streams import MatchingStreams
from hydromodpy.hydrology.pyhelp.pyhelp_netcdf import preprocessing_pyhelp
wbt = whitebox.WhiteboxTools()
wbt.verbose = False


# ============================================================================
# COMPLETE MODFLOW - EnchaÃ®ne: preprocessing â†’ processing â†’ postprocessing
# ============================================================================

def complete_modflow(geographic,flow,domain, hydraulic, settings, climatic,msl_value,
                    model_name, bin_path, workspace,config,cfg):
    """
    Complete MODFLOW workflow: Pre-processing -> Processing -> Post-processing

    Enchaine directement les 3 etapes: preprocessing, processing, postprocessing

    Parameters
    ----------
    geographic : Geographic object
    flow : Flow object
    domain : Domain object
    hydraulic : Hydraulic object
    settings : Settings object
    climatic : Climatic object
    msl_value : float or None
        Mean sea level value in metres.
    workspace : Workspace-like object
    model_name : str
        Model identification name
    hk_value : float
        Hydraulic conductivity value
    bin_path : str
        Path to MODFLOW binaries
    config : dict
        Configuration with ‘processing’ and ‘postprocessing_modflow’ keys

    Returns
    -------
    dict
        Result dictionary with keys: model_modflow, success, model_name
    """
    print(f"\n{'='*70}")
    print(f"MODFLOW WORKFLOW: {model_name}")
    print(f"{'='*70}")

    try:
        # Update hydraulic and settings
        #hydraulic.update_hk(hk_value)
        settings.update_model_name(model_name)
        settings.update_check_model(
            check_grid=config.get("postprocessing_modflow", {}).get("check_grid", True)
        )
        # Determine model folder
        model_folder = workspace.simulations_folder

        # Create Modflow instance (like example12.py)
        print("Creating MODFLOW model...")
        model_modflow = Modflow(
            geographic,
            flow=flow,
            domain=domain,
            model_folder=model_folder,
            model_name=settings.model_name,
            bin_path=bin_path,
            # Model settings
           #box=settings.box,
            sink_fill=settings.sink_fill,
            dis_perlen=settings.dis_perlen,
            # Output settings
            check_grid=settings.check_grid,
            # Boundary settings
            sea_level=msl_value,
            # Climatic settings
            recharge=climatic.recharge,
            first_clim=climatic.first_clim,
        )

        # Preprocessing
        print("  Preprocessing MODFLOW...")
        model_modflow.pre_processing()
        # --- AJOUT 1 : SAUVEGARDE PICKLE (Avant le calcul) ---
        print("  Saving model state (Pickle)...")
        dictio = {
            'list_model_name': [model_name],
            'list_model_modflow': [model_modflow]
        }
        # On crÃ©e le dossier du modÃ¨le s'il n'existe pas encore
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
                    accumulation_flux=True,
                    watertable_depth=True,
                    intermittency_weekly=False,
                    intermittency_monthly=True,
                    intermittency_yearly=False,
                    export_all_tif=False,
                )
            )

        return {'model_modflow': model_modflow, 'success': success, 'model_name': model_name}

    except Exception as e:
        print(f"MODFLOW Error: {e}")
        import traceback
        traceback.print_exc()
        return {'model_modflow': None, 'success': False, 'model_name': model_name}
# ============================================================================
# COMPLETE MODPATH - EnchaÃ®ne: preprocessing â†’ processing â†’ postprocessing â†’ filtering
# ============================================================================

def complete_modpath(domain, transport, solver_engine, workspace, vers,
                     model_modpath=None):
    """
    Complete MODPATH workflow: Pre-processing â†’ Processing â†’ Post-processing â†’ Filtering

    EnchaÃ®ne directement les Ã©tapes: preprocessing, processing, postprocessing, filt_processing

    Parameters
    ----------
    geographic : Geographic object
    settings : Settings object
    model_modflow : Modflow object
    workspace : Workspace-like object
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

    if not model_modflow:
        print("âœ— MODPATH skipped (MODFLOW not available)\n")
        return {'model_modpath': None, 'success': False}

    if not hasattr(model_modflow, 'mf'):
        print("âœ— MODPATH skipped (requires MODFLOW-NWT / solver_engine='nwt')\n")
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

        # Processing
        print("  Processing MODPATH...")
        processing_params = config.get('processing', {'write_model': True, 'run_model': True}) if config else {'write_model': True, 'run_model': True}
        success_modpath = model_modpath.processing(**processing_params)

        # Postprocessing
        if success_modpath:
            print("  Postprocessing MODPATH...")
            postproc_params = config.get('post_processing', {}) if config else {}

            # Default parameters (from example12.py)
            default_postproc = {
                'ending_point': True,
                'starting_point': True,
                'pathlines_shp': True,
                'particles_shp': True,
                'random_id': None
            }
            postproc_params = {**default_postproc, **postproc_params}
            model_modpath.post_processing(model_modpath, **postproc_params)

            # Filtering
            print("  Filtering MODPATH results...")
            filt_params = config.get('filt_processing', {}) if config else {}

            # Default parameters (from example12.py)
            default_filt = {
                'norm_flux': True,
                'filt_time': True,
                'filt_seep': True,
                'filt_inout': True,
                'calc_rtd': False,
                'random_id': None
            }
            filt_params = {**default_filt, **filt_params}
            model_modpath.filt_processing(model_modpath, **filt_params)

        print("âœ“ MODPATH completed\n")
        return {'model_modpath': model_modpath, 'success': True}

    except Exception as e:
        import traceback
        print(f"âœ— MODPATH error: {e}")
        traceback.print_exc()
        return {'model_modpath': None, 'success': False}


# ============================================================================
# COMPLETE MT3DMS - EnchaÃ®ne: preprocessing â†’ processing â†’ postprocessing
# ============================================================================

def complete_mt3dms(geographic, climatic, model_modflow,domain, workspace,transport, solver_engine,vers,
                   scenario='s1'):
    """
    Complete MT3DMS workflow: Pre-processing â†’ Processing â†’ Post-processing

    EnchaÃ®ne directement les 3 Ã©tapes: preprocessing, processing, postprocessing

    Parameters
    ----------
    geographic : Geographic object
    climatic : Climatic object
    model_modflow : Modflow object
    workspace : Workspace-like object
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
        print("âœ— MT3DMS skipped (MODFLOW not available)\n")
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

            # Default parameters (from example12.py)
            default_postproc = {
                'concentration_seepage': True,
                'mass_seepage': True,
                'mass_accumulated': True,
                'export_all_tif': True
            }
            postproc_params = {**default_postproc, **postproc_params}
            model_mt3dms.post_processing(model_mt3dms, **postproc_params)

        print("âœ“ MT3DMS completed\n")
        return {'model_mt3dms': model_mt3dms, 'success': True}

    except Exception as e:
        import traceback
        print(f"âœ— MT3DMS error: {e}")
        traceback.print_exc()
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



