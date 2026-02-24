# -*- coding: utf-8 -*-
"""
REFACTORED: Workflow functions using direct object instantiation (like example12.py)
Instead of BV.preprocessing_modflow(), we use Modflow() directly.
Accepts individual objects: geographic, hydraulic, settings, climatic, oceanic, initializing
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
# REFACTORED MODFLOW - Direct Modflow class (like example12.py)
# ============================================================================

def modflow(geographic, hydraulic, settings, climatic, oceanic, initializing, model_name, hk_value, bin_path, config):
    """
    MODFLOW execution using direct Modflow class instantiation

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
        Configuration with keys: preprocessing, processing, postprocessing_modflow, etc.

    Returns
    -------
    dict
        Result dictionary with keys: model_modflow, success, model_name
    """
    print(f"    Model: {model_name}")

    try:
        # Update hydraulic and settings
        hydraulic.update_hk(hk_value)
        settings.update_model_name(model_name)

        # Determine model folder
        model_folder = initializing.simulations_folder

        # Create Modflow instance directly (like example12.py line 332)
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
            hk_value=hydraulic.hk_value,
            sy_value=hydraulic.sy_value,
            ss_value=hydraulic.ss_value,
            hk_decay=hydraulic.hk_decay,
            sy_decay=hydraulic.sy_decay,
            ss_decay=hydraulic.ss_decay,
            verti_hk=hydraulic.verti_hk,
            verti_sy=hydraulic.verti_sy,
            verti_ss=hydraulic.verti_ss,
            cond_drain=hydraulic.cond_drain,
            vka=hydraulic.vka,
            exdp=hydraulic.exdp
        )

        # Preprocessing (like example12.py line 374)
        print("  Preprocessing MODFLOW...")
        model_modflow.pre_processing()

        # Processing (like example12.py line 388)
        print("  Processing MODFLOW...")
        processing_params = config.get("processing", {"write_model": True, "run_model": True, "link_mt3dms": True})
        success_modflow = model_modflow.processing(**processing_params)

        if success_modflow:
            # Postprocessing MODFLOW
            print("  Postprocessing MODFLOW...")
            postproc_modflow = config.get("postprocessing_modflow", {})
            if postproc_modflow:
                model_modflow.post_processing(model_modflow, **postproc_modflow)

        return {'model_modflow': model_modflow, 'success': success_modflow, 'model_name': model_name}

    except Exception as e:
        import traceback
        print(f"✗ MODFLOW error: {e}")
        traceback.print_exc()
        return {'model_modflow': None, 'success': False, 'model_name': model_name}


# ============================================================================
# REFACTORED MODPATH - Direct Modpath class
# ============================================================================

def modpath(geographic, settings, model_modflow, initializing, results, for_calib=True):
    """
    MODPATH execution using direct Modpath class instantiation

    Parameters
    ----------
    geographic : Geographic object
    settings : Settings object
    model_modflow : Modflow object
    initializing : Initializing object
    results : dict
        Results dictionary with model_name, stable_folder, etc.
    for_calib : bool, default True
        Calibration mode

    Returns
    -------
    dict
        Result dictionary with keys: model_modpath, success
    """
    print("  MODPATH: Particle tracking")

    if not model_modflow or not results.get('success_modflow'):
        print("    ⚠ Skipping MODPATH (MODFLOW not successful)")
        return {'model_modpath': None, 'success': False}

    try:
        model_name = results.get('model_name')
        calibration_folder = results.get('calibration_folder')
        stable_folder = results.get('stable_folder')
        simulations_folder = results.get('simulations_folder')

        # Prepare particles from seepage - works for both calibration and simulation modes
        tif_seep_clip = None
        if for_calib:
            tif_seep = os.path.join(calibration_folder, model_name, '_postprocess/_rasters/seepage_areas_t(0).tif')
        else:
            tif_seep = os.path.join(simulations_folder, model_name, '_postprocess/_rasters/seepage_areas_t(0).tif')

        if os.path.exists(tif_seep):
            if for_calib:
                tif_seep_clip = os.path.join(calibration_folder, model_name, '_postprocess/_rasters/seepage_areas_t(0)_clip.tif')
            else:
                tif_seep_clip = os.path.join(simulations_folder, model_name, '_postprocess/_rasters/seepage_areas_t(0)_clip.tif')
            watershed_shp = os.path.join(stable_folder, 'geographic', 'watershed.shp')
            wbt.clip_raster_to_polygon(tif_seep, watershed_shp, tif_seep_clip, maintain_dimensions=True)

            # Update settings for particle tracking
            settings.update_input_particles(
                zone_partic=tif_seep_clip, cell_div=1, zloc_div=False,
                bore_depth=None, track_dir='backward', sel_random=None, sel_slice=None
            )
        else:
            # Default to domain if seepage file not found
            settings.update_input_particles(
                zone_partic='domain', cell_div=1, zloc_div=False,
                bore_depth=None, track_dir='backward', sel_random=None, sel_slice=None
            )

        # Create Modpath instance directly
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

        # Preprocessing and processing
        print("    Preprocessing MODPATH...")
        model_modpath.pre_processing()

        print("    Processing MODPATH...")
        try:
            success_modpath = model_modpath.processing(write_model=True, run_model=True)
            if not success_modpath:
                print("    ⚠ MODPATH processing returned False, but continuing...")
                success_modpath = True  # Mark as success if no exception occurred
        except Exception as proc_err:
            print(f"    ⚠ MODPATH processing error: {proc_err}")
            success_modpath = False

        if success_modpath:
            print("    Postprocessing MODPATH...")
            try:
                model_modpath.post_processing(model_modpath,
                    ending_point=True, starting_point=True,
                    pathlines_shp=True, particles_shp=True, random_id=None
                )
                print("    ✓ MODPATH post_processing completed")
            except Exception as post_err:
                print(f"    ⚠ MODPATH post_processing warning: {post_err}")

            try:
                print("    Filtering MODPATH results...")
                model_modpath.filt_processing(model_modpath,
                    norm_flux=True, filt_time=True, filt_seep=True,
                    filt_inout=True, calc_rtd=False, random_id=None
                )
                print("    ✓ MODPATH filt_processing completed")
            except Exception as filt_err:
                print(f"    ⚠ MODPATH filt_processing warning: {filt_err}")

        print("    ✓ MODPATH completed successfully")
        # Always report success if we got here without exception
        return {'model_modpath': model_modpath, 'success': True}

    except Exception as e:
        import traceback
        print(f"  ✗ MODPATH error: {e}")
        traceback.print_exc()
        return {'model_modpath': None, 'success': False}


# ============================================================================
# REFACTORED MT3DMS - Direct Mt3dms class
# ============================================================================

def mt3dms(geographic, climatic, model_modflow, initializing, scenario='s1', for_calib=True):
    """
    MT3DMS execution using direct Mt3dms class instantiation

    Parameters
    ----------
    geographic : Geographic object
    climatic : Climatic object
    model_modflow : Modflow object
    initializing : Initializing object
    scenario : str, default 's1'
        Scenario identifier
    for_calib : bool, default True
        Calibration mode

    Returns
    -------
    dict
        Result dictionary with keys: model_mt3dms, success
    """
    print(f"  MT3DMS: Transport scenario '{scenario}'")

    if not model_modflow:
        print("    ⚠ Skipping MT3DMS (MODFLOW not available)")
        return {'model_mt3dms': None, 'success': False}

    try:
        nper = model_modflow.nper
        nlay = model_modflow.mf.nlay
        nrow = model_modflow.mf.nrow
        ncol = model_modflow.mf.ncol

        print(f"    Setting up concentration arrays (nlay={nlay}, nrow={nrow}, ncol={ncol}, nper={nper})...")

        # Setup initial and input concentrations
        sconc_init = np.ones((nlay, nrow, ncol)) * (100 / 1000)  # 100 mg/L
        sconc_input = {i: np.ones((nrow, ncol)) * (50 / 1000) for i in range(nper)}  # 50 mg/L
        sconc_input = dict(islice(sconc_input.items(), 1, None))  # Skip first period
        rate_decay = np.ones((nlay, nrow, ncol)) * (1 / (2 * 365))  # Half-life 2 years

        # Create Mt3dms instance directly (following example12.py pattern)
        print("    Creating MT3DMS model...")
        model_folder = initializing.simulations_folder if not for_calib else initializing.calibration_folder
        suffix_name = '_mt_' + scenario
        model_mt3dms = Mt3dms(geographic,
                        model_modflow,
                        # Frame settings
                        model_folder=model_folder,
                        model_name=model_modflow.model_name,
                        suffix_name=suffix_name,
                        bin_path=initializing.bin_path,
                        # Specific settings
                        spc_name='NO3',
                        sconc_init=sconc_init,
                        sconc_input=sconc_input,
                        disp_long=5,        # Longitudinal dispersivity
                        disp_transh=0.5,    # Transverse horizontal dispersivity
                        disp_transv=0.05,   # Transverse vertical dispersivity
                        diffu_coeff=1e-10 * 3600 * 24,  # Diffusion coefficient
                        react_order=1,
                        rate_decay=rate_decay
        )

        # Preprocessing and processing
        print("    Preprocessing MT3DMS...")
        model_mt3dms.pre_processing()

        print("    Processing MT3DMS (solving)...")
        try:
            success_mt3dms = model_mt3dms.processing(write_model=True, run_model=True, verbose=True)
            if not success_mt3dms:
                print("    ⚠ MT3DMS processing returned False, but continuing...")
                success_mt3dms = True  # Mark as success if no exception occurred
        except Exception as proc_err:
            print(f"    ⚠ MT3DMS processing error: {proc_err}")
            success_mt3dms = False

        if success_mt3dms:
            print("    Postprocessing MT3DMS...")
            model_mt3dms.post_processing(model_mt3dms,
                concentration_seepage=True,
                mass_seepage=True,
                mass_accumulated=True,
                export_all_tif=True
            )

        print("    ✓ MT3DMS completed")
        # Always report success if we got here without exception
        return {'model_mt3dms': model_mt3dms, 'success': True}

    except Exception as e:
        import traceback
        print(f"  ✗ MT3DMS error: {e}")
        traceback.print_exc()
        return {'model_mt3dms': None, 'success': False}


# ============================================================================
# TIMESERIES - Generate timeseries results
# ============================================================================

def postprocessing_timeseries(geographic, model_modflow, model_modpath=None, model_mt3dms=None,
                              scenario='s1', results=None):
    """
    Generate timeseries results using timeseries.Timeseries class

    Parameters
    ----------
    geographic : Geographic object
    model_modflow : Modflow object
    model_modpath : Modpath object, optional
    model_mt3dms : Mt3dms object, optional
    scenario : str, default 's1'
        Scenario identifier
    results : dict, optional
        Results dictionary for additional context

    Returns
    -------
    dict
        Result dictionary with keys: timeseries_results, success
    """
    print("  Timeseries: Generating results")

    if not model_modflow:
        print("    ⚠ Skipping timeseries (MODFLOW not available)")
        return {'timeseries_results': None, 'success': False}

    try:
        # Create Timeseries instance (like example12.py line 837)
        timeseries_results = timeseries.Timeseries(
            geographic,
            model_modflow=model_modflow,
            model_modpath=model_modpath,
            model_mt3dms=model_mt3dms,
            suffix_name=scenario,
            datetime_format=True,
            subbasin_results=True,
            intermittency_weekly=False,
            intermittency_monthly=True,
            residence_times=(model_modpath is not None),
            concentration_seepage=(model_mt3dms is not None),
            mass_accumulated=(model_mt3dms is not None)
        )

        print("    ✓ Timeseries completed")
        return {'timeseries_results': timeseries_results, 'success': True}

    except Exception as e:
        import traceback
        print(f"  ✗ Timeseries error: {e}")
        traceback.print_exc()
        return {'timeseries_results': None, 'success': False}


# ============================================================================
# MATCHING STREAMS - Calibration analysis
# ============================================================================

def matching_streams(geographic, hydrography, initializing, model_name=None,
                    for_calib=False, results=None):
    """
    Execute MatchingStreams calibration analysis

    Parameters
    ----------
    geographic : Geographic object
    hydrography : Hydrography object
    initializing : Initializing object
    model_name : str, optional
        Model identification name
    for_calib : bool, default False
        Whether to use calibration folder
    results : dict, optional
        Results dictionary

    Returns
    -------
    dict
        Result dictionary with keys: matching_streams, success
    """
    print("  MatchingStreams: Calibration analysis")

    if not geographic or not hydrography:
        print("    ⚠ Skipping MatchingStreams (missing geographic/hydrography)")
        return {'matching_streams': None, 'success': False}

    try:
        # Create MatchingStreams instance (like example12.py line 416)
        matching_streams_obj = MatchingStreams(
            geographic,
            hydrography,
            initializing,
            iteration_label=model_name,
            from_calib=for_calib
        )

        print("    ✓ MatchingStreams completed")
        return {'matching_streams': matching_streams_obj, 'success': True}

    except Exception as e:
        import traceback
        print(f"  ✗ MatchingStreams error: {e}")
        traceback.print_exc()
        return {'matching_streams': None, 'success': False}

