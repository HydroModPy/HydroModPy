# -*- coding: utf-8 -*-
"""
COMPLETE MODELING WORKFLOW - Generic Pipeline
Enchaîne: MODFLOW → MODPATH → MT3DMS
3 fonctions séparées: complete_modflow(), complete_modpath(), complete_mt3dms()
"""

import os
import numpy as np
import whitebox
from itertools import islice
from pathlib import Path

# Direct class imports (like example12.py)
from hydromodpy.modeling.modflow import Modflow
from hydromodpy.modeling.modpath import Modpath
from hydromodpy.modeling.mt3dms import Mt3dms
from hydromodpy.modeling import timeseries, netcdf
from hydromodpy.calibration_legacy.matching_stream import MatchingStreams

wbt = whitebox.WhiteboxTools()
wbt.verbose = False


# ============================================================================
# COMPLETE MODFLOW - Enchaîne: preprocessing → processing → postprocessing
# ============================================================================

def complete_modflow(geographic, hydraulic, settings, climatic, oceanic, initializing,
                    model_name, hk_value, bin_path, config):
    """
    Complete MODFLOW workflow: Pre-processing → Processing → Post-processing

    Enchaîne directement les 3 étapes: preprocessing, processing, postprocessing

    Parameters
    ----------
    geographic : Geographic object
    hydraulic : Hydraulic object
    settings : Settings object
    climatic : Climatic object
    oceanic : Oceanic object
    initializing : Initializing object
    model_name : str
        Model identification name
    hk_value : float
        Hydraulic conductivity value
    bin_path : str
        Path to MODFLOW binaries
    config : dict
        Configuration with 'processing' and 'postprocessing_modflow' keys

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
        hydraulic.update_hk(hk_value)
        settings.update_model_name(model_name)

        # Determine model folder
        model_folder = initializing.simulations_folder

        # Create Modflow instance (like example12.py)
        print("Creating MODFLOW model...")
        model_modflow = Modflow(
            geographic,
            model_folder=model_folder,
            model_name=model_name,
            bin_path=bin_path,
            # Model settings
            box=settings.box,
            sink_fill=settings.sink_fill,
            sim_state=settings.sim_state,
            dis_perlen=settings.dis_perlen,
            # Well settings
            well_coords=settings.well_coords,
            well_fluxes=settings.well_fluxes,
            # Output settings
            plot_cross=settings.plot_cross,
            cross_ylim=settings.cross_ylim,
            check_grid=settings.check_grid,
            # Boundary settings
            sea_level=oceanic.MSL if oceanic else None,
            bc_left=settings.bc_left,
            bc_right=settings.bc_right,
            # Climatic settings
            recharge=climatic.recharge,
            runoff=climatic.runoff,
            first_clim=climatic.first_clim,
            # Hydraulic settings
            bottom=hydraulic.bottom,
            thick=hydraulic.thick,
            nlay=hydraulic.nlay,
            lay_decay=hydraulic.lay_decay,
            cond_drain=hydraulic.cond_drain,
        )

        # Preprocessing
        print("  Preprocessing MODFLOW...")
        model_modflow.pre_processing()

        # Processing
        print("  Processing MODFLOW...")
        processing_params = config.get("processing", {"write_model": True, "run_model": True, "link_mt3dms": True})
        success_modflow = model_modflow.processing(**processing_params)

        # Postprocessing
        if success_modflow:
            print("  Postprocessing MODFLOW...")
            postproc_params = config.get("postprocessing_modflow", {})

            # Default parameters (from example12.py)
            default_params = {
                'watertable_elevation': True,
                'seepage_areas': True,
                'outflow_drain': True,
                'accumulation_flux': True,
                'watertable_depth': True,
                'groundwater_flux': False,
                'groundwater_storage': False,
                'intermittency_weekly': False,
                'intermittency_monthly': True,
                'intermittency_yearly': False,
                'export_all_tif': False
            }

            # Merge config with defaults (config overrides defaults)
            postproc_params = {**default_params, **postproc_params}
            model_modflow.post_processing(model_modflow, **postproc_params)

        print("✓ MODFLOW completed\n")
        return {'model_modflow': model_modflow, 'success': success_modflow, 'model_name': model_name}

    except Exception as e:
        import traceback
        print(f"✗ MODFLOW error: {e}")
        traceback.print_exc()
        return {'model_modflow': None, 'success': False, 'model_name': model_name}


# ============================================================================
# COMPLETE MODPATH - Enchaîne: preprocessing → processing → postprocessing → filtering
# ============================================================================

def complete_modpath(geographic, settings, model_modflow, initializing, model_name,
                    for_calib=False, config=None):
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
    print(f"MODPATH WORKFLOW: {model_name}")
    print(f"{'='*70}")

    if not model_modflow:
        print("✗ MODPATH skipped (MODFLOW not available)\n")
        return {'model_modpath': None, 'success': False}

    try:
        stable_folder = initializing.stable_folder
        simulations_folder = initializing.simulations_folder
        calibration_folder = initializing.calibration_folder

        # Prepare particles from seepage
        working_folder = calibration_folder if for_calib else simulations_folder
        tif_seep = os.path.join(working_folder, model_name, '_postprocess/_rasters/seepage_areas_t(0).tif')
        tif_seep_clip = os.path.join(working_folder, model_name, '_postprocess/_rasters/seepage_areas_t(0)_clip.tif')

        if os.path.exists(tif_seep):
            print(f"  Clipping seepage areas to watershed...")
            watershed_shp = os.path.join(stable_folder, 'geographic', 'watershed.shp')
            wbt.clip_raster_to_polygon(tif_seep, watershed_shp, tif_seep_clip, maintain_dimensions=True)
            zone_partic_param = tif_seep_clip
        else:
            zone_partic_param = 'domain'

        # Get preprocessing params
        preproc_params = config.get('preprocessing', {}) if config else {}
        cell_div = preproc_params.get('cell_div', 1)
        zloc_div = preproc_params.get('zloc_div', False)
        bore_depth = preproc_params.get('bore_depth', None)
        track_dir = preproc_params.get('track_dir', 'backward')
        sel_random = preproc_params.get('sel_random', None)
        sel_slice = preproc_params.get('sel_slice', None)

        # Update settings
        settings.update_input_particles(
            zone_partic=zone_partic_param, cell_div=cell_div, zloc_div=zloc_div,
            bore_depth=bore_depth, track_dir=track_dir, sel_random=sel_random, sel_slice=sel_slice
        )

        # Create Modpath instance
        print("Creating MODPATH model...")
        model_folder = initializing.calibration_folder if for_calib else initializing.simulations_folder
        model_modpath = Modpath(geographic,
                                model_modflow,
                                model_folder=model_folder,
                                model_name=model_modflow.model_name,
                                bin_path=initializing.bin_path,
                                zone_partic=settings.zone_partic,
                                cell_div=settings.cell_div,
                                zloc_div=settings.zloc_div,
                                bore_depth=settings.bore_depth,
                                track_dir=settings.track_dir,
                                sel_random=settings.sel_random,
                                sel_slice=settings.sel_slice)

        # Preprocessing
        print("  Preprocessing MODPATH...")
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

        print("✓ MODPATH completed\n")
        return {'model_modpath': model_modpath, 'success': True}

    except Exception as e:
        import traceback
        print(f"✗ MODPATH error: {e}")
        traceback.print_exc()
        return {'model_modpath': None, 'success': False}


# ============================================================================
# COMPLETE MT3DMS - Enchaîne: preprocessing → processing → postprocessing
# ============================================================================

def complete_mt3dms(geographic, climatic, model_modflow, initializing, model_name,
                   scenario='s1', for_calib=False, transport=None, config=None):
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
    print(f"MT3DMS WORKFLOW: {model_name} - scenario '{scenario}'")
    print(f"{'='*70}")

    if not model_modflow:
        print("✗ MT3DMS skipped (MODFLOW not available)\n")
        return {'model_mt3dms': None, 'success': False}

    try:
        nper = model_modflow.nper
        nlay = model_modflow.mf.nlay
        nrow = model_modflow.mf.nrow
        ncol = model_modflow.mf.ncol

        print(f"  Setting up concentration arrays (nlay={nlay}, nrow={nrow}, ncol={ncol}, nper={nper})...")

        # Get transport parameters from config, then from transport object, then defaults
        preproc_params = config.get('preprocessing', {}) if config else {}

        spc_name = preproc_params.get('spc_name') or (transport.spc_name if transport else 'NO3')
        disp_long = preproc_params.get('disp_long', transport.disp_long if transport else 0)
        disp_transh = preproc_params.get('disp_transh', transport.disp_transh if transport else 0)
        disp_transv = preproc_params.get('disp_transv', transport.disp_transv if transport else 0)
        diffu_coeff = preproc_params.get('diffu_coeff', transport.diffu_coeff if transport else 1e-10 * 3600 * 24)
        react_order = preproc_params.get('react_order', transport.react_order if transport else 1)
        plot_conc = preproc_params.get('plot_conc', transport.plot_conc if transport else True)

        # Concentration arrays from transport object
        if transport is not None:
            sconc_init = transport.sconc_init
            sconc_input = transport.sconc_input
            rate_decay = transport.rate_decay
        else:
            # Default values
            sconc_init = np.ones((nlay, nrow, ncol)) * (100 / 1000)
            sconc_input = {i: np.ones((nrow, ncol)) * (50 / 1000) for i in range(nper)}
            sconc_input = dict(islice(sconc_input.items(), 1, None))
            rate_decay = np.ones((nlay, nrow, ncol)) * (1 / (2 * 365))

        # Create Mt3dms instance
        print("Creating MT3DMS model...")
        model_folder = initializing.simulations_folder if not for_calib else initializing.calibration_folder
        suffix_name = '_mt_' + scenario
        model_mt3dms = Mt3dms(geographic,
                        model_modflow,
                        model_folder=model_folder,
                        model_name=model_modflow.model_name,
                        suffix_name=suffix_name,
                        bin_path=initializing.bin_path,
                        spc_name=spc_name,
                        sconc_init=sconc_init,
                        sconc_input=sconc_input,
                        disp_long=disp_long,
                        disp_transh=disp_transh,
                        disp_transv=disp_transv,
                        diffu_coeff=diffu_coeff,
                        react_order=react_order,
                        rate_decay=rate_decay,
                        plot_conc=plot_conc
        )

        # Preprocessing
        print("  Preprocessing MT3DMS...")
        model_mt3dms.pre_processing()

        # Processing
        print("  Processing MT3DMS...")
        processing_params = config.get('processing', {'write_model': True, 'run_model': True, 'verbose': True}) if config else {'write_model': True, 'run_model': True, 'verbose': True}
        success_mt3dms = model_mt3dms.processing(**processing_params)

        # Postprocessing
        if success_mt3dms:
            print("  Postprocessing MT3DMS...")
            postproc_params = config.get('post_processing', {}) if config else {}

            # Default parameters (from example12.py)
            default_postproc = {
                'concentration_seepage': True,
                'mass_seepage': True,
                'mass_accumulated': True,
                'export_all_tif': True
            }
            postproc_params = {**default_postproc, **postproc_params}
            model_mt3dms.post_processing(model_mt3dms, **postproc_params)

        print("✓ MT3DMS completed\n")
        return {'model_mt3dms': model_mt3dms, 'success': True}

    except Exception as e:
        import traceback
        print(f"✗ MT3DMS error: {e}")
        traceback.print_exc()
        return {'model_mt3dms': None, 'success': False}


# ============================================================================
# COMPLETE TIMESERIES - Generate timeseries results (postprocessing)
# ============================================================================

def complete_timeseries(geographic, model_modflow, model_modpath=None, model_mt3dms=None,
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
        print("✗ TIMESERIES skipped (MODFLOW not available)\n")
        return {'timeseries_results': None, 'success': False}

    try:
        print("Creating Timeseries object...")

        # Create Timeseries instance (like example12.py line 856)
        # suffix_name only when MT3DMS is present, otherwise None for generic _simulated_timeseries.csv
        suffix_name = scenario if model_mt3dms is not None else None
        timeseries_results = timeseries.Timeseries(
            geographic,
            model_modflow=model_modflow,
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

        print("✓ TIMESERIES completed\n")
        return {'timeseries_results': timeseries_results, 'success': True}

    except Exception as e:
        import traceback
        print(f"✗ TIMESERIES error: {e}")
        traceback.print_exc()
        return {'timeseries_results': None, 'success': False}
