# -*- coding: utf-8 -*-
"""
General workflow functions for MODFLOW, MODPATH, MT3DMS, and timeseries postprocessing.
Encapsulates preprocessing, processing, and postprocessing in single functions.
Reusable across all examples.
"""

import os
import numpy as np
import whitebox
from itertools import islice

# HydroModPy modeling imports (used indirectly through BV Watershed object methods)
from hydromodpy.modeling.modflow import Modflow
from hydromodpy.modeling.modpath import Modpath
from hydromodpy.modeling.mt3dms import Mt3dms
from hydromodpy.modeling import timeseries

wbt = whitebox.WhiteboxTools()
wbt.verbose = False


# ============================================================================
# GENERIC MODELING METHODS - Configuration-based workflow
# ============================================================================

def modflow(BV, model_name, hk_value, config):
    """
    GENERIC MODFLOW execution - reusable for all examples

    Configuration-driven approach with preprocessing, processing, and postprocessing
    parameters supplied via config dictionary.

    Parameters
    ----------
    BV : Watershed object
+        HydroModPy Watershed object (must be configured with settings)
    model_name : str
        Model identification name
    hk_value : float
        Hydraulic conductivity value
    config : dict
        Configuration dictionary with keys:
        - 'preprocessing': dict of preprocessing parameters (e.g., for_calib)
        - 'processing': dict of processing parameters
        - 'postprocessing_modflow': dict of MODFLOW postprocessing parameters
        - 'postprocessing_timeseries': dict of timeseries postprocessing parameters
        - 'postprocessing_netcdf': bool to enable netCDF export

    Returns
    -------
    dict
        Result dictionary with keys: model_modflow, success, model_name
    """
    print(f"    Model: {model_name}")

    BV.hydraulic.update_hk(hk_value)
    BV.settings.update_model_name(model_name)

    # Get preprocessing parameters, default to for_calib=True if not specified
    preprocessing_params = config.get("preprocessing", {})

    # Call preprocessing_modflow - settings should already be configured via parametrization()
    # preprocessing_modflow only uses the for_calib parameter from config
    if preprocessing_params:
        model_modflow = BV.preprocessing_modflow(**preprocessing_params)
    else:
        # Call with no arguments - uses BV.settings configured values
        model_modflow = BV.preprocessing_modflow()

    if model_modflow is None:
        print(f"Preprocessing failed")
        return {'model_modflow': None, 'success': False, 'model_name': model_name}

    # Get processing parameters, default reasonable values
    processing_params = config.get("processing", {"write_model": True, "run_model": True})
    success_modflow = BV.processing_modflow(model_modflow, **processing_params)

    if success_modflow:
        # Postprocessing MODFLOW
        postproc_modflow = config.get("postprocessing_modflow", {})
        if postproc_modflow:
            BV.postprocessing_modflow(model_modflow, **postproc_modflow)

        # Postprocessing timeseries
        postproc_ts = config.get("postprocessing_timeseries", {})
        if postproc_ts:
            BV.postprocessing_timeseries(model_modflow=model_modflow, model_modpath=None,
                                         model_mt3dms=None, **postproc_ts)

        # Postprocessing netCDF
        if config.get("postprocessing_netcdf", False):
            datetime_format = config.get("postprocessing_timeseries", {}).get("datetime_format", False)
            BV.postprocessing_netcdf(model_modflow, datetime_format=datetime_format)

    return {'model_modflow': model_modflow, 'success': success_modflow, 'model_name': model_name}


def modpath(BV, results, for_calib=True):
    """
    GENERIC MODPATH execution - reusable for all examples

    Particle tracking workflow with configuration from results dictionary.

    Parameters
    ----------
    BV : Watershed object
        HydroModPy Watershed object
    results : dict
        Results dictionary containing:
        - 'model_modflow': MODFLOW model object
        - 'success_modflow': MODFLOW success flag
        - 'calibration_folder': path to calibration folder
        - 'model_name': model identification name
        - 'stable_folder': path to stable folder
    for_calib : bool, default True
        Calibration mode

    Returns
    -------
    dict
        Result dictionary with keys: model_modpath, success, BV
    """
    print("    MODPATH: Particle tracking")

    model_modflow = results.get('model_modflow')
    if not model_modflow or not results.get('success_modflow'):
        print("Skipping MODPATH (MODFLOW not successful)")
        return {'model_modpath': None, 'success': False, 'BV': BV}

    try:
        BV.add_settings()

        if for_calib:
            calibration_folder = results.get('calibration_folder')
            model_name = results.get('model_name')
            tif_seep = os.path.join(calibration_folder, model_name, '_postprocess/_rasters/seepage_areas_t(0).tif')
            stable_folder = results.get('stable_folder')

            if os.path.exists(tif_seep):
                tif_seep_clip = os.path.join(calibration_folder, model_name, '_postprocess/_rasters/seepage_areas_t(0)_clip.tif')
                wbt.clip_raster_to_polygon(tif_seep, os.path.join(stable_folder, 'geographic', 'watershed.shp'),
                                          tif_seep_clip, maintain_dimensions=True)
                BV.settings.update_input_particles(zone_partic=tif_seep_clip, cell_div=1, zloc_div=False,
                                                  bore_depth=None, track_dir='backward', sel_random=None, sel_slice=None)

        model_modpath = BV.preprocessing_modpath(model_modflow, for_calib=for_calib)
        success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)

        if success_modpath:
            BV.postprocessing_modpath(model_modpath, ending_point=True, starting_point=True,
                                     pathlines_shp=True, particles_shp=True, random_id=None)
            BV.filtprocessing_modpath(model_modpath, norm_flux=True, filt_time=True, filt_seep=True,
                                     filt_inout=True, calc_rtd=False, random_id=None)

        return {'model_modpath': model_modpath, 'success': success_modpath, 'BV': BV}
    except Exception as e:
        print(f"MODPATH error: {e}")
        return {'model_modpath': None, 'success': False, 'BV': BV}
        results['BV'] = BV
        return results



def mt3dms(BV, results, scenario='s1', for_calib=True):
    """
    GENERIC MT3DMS execution - reusable for all examples

    Contaminant transport workflow with configuration from results dictionary.

    Parameters
    ----------
    BV : Watershed object
        HydroModPy Watershed object
    results : dict
        Results dictionary containing:
        - 'model_modflow': MODFLOW model object
        - 'success_modflow': MODFLOW success flag
    scenario : str, default 's1'
        Scenario identifier
    for_calib : bool, default True
        Calibration mode

    Returns
    -------
    dict
        Result dictionary with keys: model_mt3dms, success, BV
    """
    print(f"MT3DMS: Transport scenario '{scenario}'")

    model_modflow = results.get('model_modflow')
    if not model_modflow or not results.get('success_modflow'):
        print("Skipping MT3DMS (MODFLOW not successful)")
        return {'model_mt3dms': None, 'success': False, 'BV': BV}

    try:
        print("Adding transport module...")
        BV.add_transport()

        nper = model_modflow.nper
        nlay = model_modflow.mf.nlay
        nrow = model_modflow.mf.nrow
        ncol = model_modflow.mf.ncol

        print(f"Setting up concentration arrays (nlay={nlay}, nrow={nrow}, ncol={ncol}, nper={nper})...")
        sconc_init = np.ones((nlay, nrow, ncol)) * (100 / 1000)
        sconc_input = {i: np.ones((nrow, ncol)) * (50 / 1000) for i in range(nper)}
        sconc_input = dict(islice(sconc_input.items(), 1, None))
        rate_decay = np.ones((nlay, nrow, ncol)) * (1 / (2 * 365))

        print("Updating MT3DMS parameters...")
        BV.transport.update_mt3dms_parameters(spc_name='NO3', sconc_init=sconc_init, sconc_input=sconc_input,
                                             disp_long=0, disp_transh=0, disp_transv=0,
                                             diffu_coeff=1e-10 * 3600 * 24, react_order=1,
                                             rate_decay=rate_decay, plot_conc=True)

        print("Running MT3DMS preprocessing...")
        model_mt3dms = BV.preprocessing_mt3dms(model_modflow, for_calib=for_calib, suffix_name=f'_mt_{scenario}')

        if model_mt3dms is None:
            print("MT3DMS preprocessing returned None")
            return {'model_mt3dms': None, 'success': False, 'BV': BV}

        print("Running MT3DMS processing (solving)...")
        success_mt3dms = BV.processing_mt3dms(model_mt3dms, write_model=True, run_model=True, verbose=True)


        print("Running MT3DMS postprocessing...")
        BV.postprocessing_mt3dms(model_mt3dms, concentration_seepage=True, mass_seepage=True,
                                    mass_accumulated=True, export_all_tif=True)

        print("MT3DMS completed successfully")
        return {'model_mt3dms': model_mt3dms, 'success': True, 'BV': BV}
    except Exception as e:
        import traceback
        print(f" MT3DMS error: {e}")
        print(f"  Traceback:\n{traceback.format_exc()}")
        return {'model_mt3dms': None, 'success': False, 'BV': BV}


def timeseries(BV, results, timeseries_config=None):
    """
    GENERIC TIMESERIES execution - reusable for all examples

    Timeseries postprocessing workflow for MODFLOW, MODPATH, and MT3DMS results.

    Parameters
    ----------
    BV : Watershed object
        HydroModPy Watershed object
    results : dict
        Results dictionary containing:
        - 'model_modflow': MODFLOW model object (required)
        - 'model_modpath': MODPATH model object (optional)
        - 'model_mt3dms': MT3DMS model object (optional)
    timeseries_config : dict, optional
        Configuration parameters for timeseries postprocessing

    Returns
    -------
    dict
        Updated results dictionary with timeseries data
    """
    timeseries_config = timeseries_config or {}

    try:
        model_modflow = results.get('model_modflow')
        model_modpath = results.get('model_modpath')
        model_mt3dms = results.get('model_mt3dms')

        if model_modflow is None:
            print("    ⚠ Timeseries requires MODFLOW model")
            return results

        BV.postprocessing_timeseries(
            model_modflow=model_modflow,
            model_modpath=model_modpath,
            model_mt3dms=model_mt3dms,
            **timeseries_config
        )

        results['timeseries_completed'] = True
        return results
    except Exception as e:
        print(f"Timeseries error: {e}")
        results['timeseries_completed'] = False
        return results


