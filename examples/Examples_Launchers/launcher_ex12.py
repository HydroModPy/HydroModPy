# -*- coding: utf-8 -*-
"""
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 * HydroModPy Launcher - Exemple 03 + Exemple 09
 * Regroupe les deux exemples avec CONFIG pour activer/désactiver les parties
"""

import sys
import os
import pickle
import numpy as np
import pandas as pd
import matplotlib as mpl
# Set matplotlib backend based on display setting
# Using 'Agg' when display_figures is False to prevent window pop-ups
# Note: CONFIG is defined later in the file, so we'll check display_figures after importing
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import imageio.v2 as imageio
import whitebox
import geopandas as gpd
import glob
from pathlib import Path
import rasterio
import rasterio.plot
import matplotlib.cm as cm
import matplotlib.colors as mcolors
from mpl_toolkits.axes_grid1 import make_axes_locatable
from itertools import islice
from PIL import Image
import base64
from io import BytesIO

try:
    import flopy.utils.binaryfile as bf
    import plotly.graph_objects as go
except ImportError:
    pass

wbt = whitebox.WhiteboxTools()
wbt.verbose = False

root_dir = str(Path(__file__).parent)
sys.path.append(root_dir)

try:
    import hydromodpy
except:
    pass

from hydromodpy import watershed_root
from hydromodpy.watershed import initializing, geographic
from hydromodpy.watershed.initializing_config import InitializingConfig
from hydromodpy.watershed.geographic_config import GeographicConfig
from hydromodpy.display import visualization_watershed, visualization_results
from hydromodpy.tools import toolbox
from hydromodpy.modeling_workflow import modflow, modpath, mt3dms, timeseries
fontprop = toolbox.plot_params(8, 15, 18, 20)


# ============================================================================
# CONFIG - CHOISIR EXEMPLE ET SECTIONS À EXÉCUTER
# ============================================================================

CONFIG = {
    "example": "ex09",  # "ex03" ou "ex09" - CHOISIS UN SEUL EXEMPLE
    "display_figures": False,  # Show matplotlib pop-ups when plotting
    "sections": {
        # Ex03 and Ex09 shared sections
        "watershed": True,          # Extraction du bassin versant
        "data": True,               # Chargement des données
        "recharge": True,           # Recharge et runoff
        "parametrization": True,    # Paramètres
        "modeling": True,           # Modélisation MODFLOW

        # Ex03 specific
        "plot": True,               # Plotting enabled (ex03_plot or ex09_plot based on example)

        # Ex09 specific (must match example_09_new.py complete workflow)
        "matching_streams": True,   # Stream occurrence calibration (ex09 only)
        "modpath": True,            # Particle tracking (ex09 only)
        "mt3dms": True,             # Transport model (ex09 only)
        "plot_streamflow": True,    # Streamflow vs observed (ex09 only)
        "plot_piezometry": True,    # Watertable depth evolution (ex09 only)
        "plot_pathlines": True,     # Residence times (ex09 only, needs MODPATH)
        "plot_concentration": True, # Animated concentration maps (ex09 only, needs MT3DMS)
        "plot_animation_interactive": True  # Interactive web animation (ex09 only)
    }
}

# Set matplotlib backend based on display_figures config
if not CONFIG.get('display_figures', False):
    mpl.use('Agg')  # Non-interactive backend to prevent window pop-ups


# ============================================================================
# PARAMÈTRES +Data Configs + PROCESS + MODFLOW
# ============================================================================

PARAMS = {
    "ex03": {
        "base_path": "examples/03S_short",  # ← SHORT version (plus rapide)
        "dem_filename": "regional dem.tif",
        "dem_coordinates": [327816.965, 6777886.670, 150, 10, 'EPSG:2154'],
        "watershed_name": "Example_03_Canut",
        "recharge_first_year": 1990,
        "recharge_last_year": 2019,
        "recharge_time_step": "D",
        # Parametrization
        "box": True,
        "sink_fill": False,
        "sim_state": "steady",
        "plot_cross": False,
        "check_grid": False,
        "dis_perlen": False,
        "recharge_monthly": [10, 20, 30, 40, 50, 60, 60, 50, 40, 30, 20, 10],
        "nlay": 5,
        "lay_decay": 1,
        "bottom": None,
        "thick": 50,
        "sy": 10 / 100,
        "cond_drain": None,
        "bc_left": None,
        "bc_right": None,
        "sea_level": "None",
        # Modeling
        "iD_set_simulations": "explorK_test1",
        "list_hyd_cond": list(np.geomspace(1e-8, 1e-3, 10)),  # in m/s (10 values)
    },
    "ex09": {
        "base_path": "examples/09S_short",  # ← SHORT version (plus rapide)
        "dem_filename": "regional dem.tif",
        "dem_coordinates": [265611.933, 6784182.776, 50, 20, 'EPSG:2154'],
        "watershed_name": "09S_short",
        "recharge_first_year": 2003,       # ← 09S_short SHORT version
        "recharge_last_year": 2003,        # ← Single year for speed
        "recharge_time_step": "M",         # ← Monthly (not Weekly)
        # Modeling
        "box": True,
        "sink_fill": False,
        "sim_state": "transient",         # ← TRANSIENT = long calcul
        "plot_cross": True,
        "cross_ylim": [0, 150],
        "check_grid": True,
        "dis_perlen": True,
        "nlay": 10,                       # ← 10 couches = long calcul
        "lay_decay": 1.2,
        "verti_hk": None,
        "verti_sy": None,
        "verti_ss": None,
        "cond_drain": None,
        "sy": 1 / 100,
        "sy_decay": 0,
        "ss": 1e-5,
        "ss_decay": 0,
        "vka": 1,
        "bottom": 0,
        "thickness": 100,
        "bc_left": None,
        "bc_right": None,
        "sea_level": "None",
        "alpha": 15,
        "n_factor": 2,
        "the_K0": 5e-5 * 24 * 3600,
        "Kmin_for_hk_decay": 1e-8 * 24 * 3600,
        "the_sy0": 2 / 100,
        "Symin_for_sy_decay": 0.1 / 100,
        "the_ss0": 1e-10,
        "Klog_transf": False,
        "vers": "TRANS1",
        # Transport (MT3DMS) settings
        "spc_name": "NO3",
        "disp_long": 5,  # Longitudinal dispersivity (m)
        "disp_transh": 0.5,  # Transverse horizontal dispersivity
        "disp_transv": 0.05,  # Transverse vertical dispersivity
        "diffu_coeff": 1e-10 * 3600 * 24,  # Molecular diffusion (L2T-1)
        "react_order": 1,  # 0: zero-order, 1: first-order
        "sconc_init_value": 100,  # Initial concentration (mg/L)
        "sconc_input_value": 50,  # Input concentration (mg/L)
        "rate_decay_value": 1 / (2 * 365),  # Decay rate (T-1) - half-life 2 years
        "plot_conc": True,
}
}
# Configuration par défaut pour chaque exemple
DATA_CONFIGS = {
    "ex03": {
        "modules": [
            {"name": "geology", "method": "add_geology",
             "args": [('types_obs', 'GEO1M.shp'), ('fields_obs', 'CODE_LEG')]},
            {"name": "hydrography", "method": "add_hydrography",
             "args": [('types_obs', ['regional stream network']), ('fields_obs', ['FID'])]},
            {"name": "hydrometry", "method": "add_hydrometry",
             "args": [('file_name', 'france hydrometric stations.shp')]},
            {"name": "intermittency", "method": "add_intermittency",
             "args": [('file_name', 'regional onde stations.shp')]},
            {"name": "subbasins", "method": "add_subbasin",
             "args": [('sub_snap_dist', 150)]}
        ],
        "visualizations": [
            {"name": "local", "method": "watershed_local",
             "dem_param": True},
            {"name": "geology", "method": "watershed_geology"},
            {"name": "dem", "method": "watershed_dem"},
            {"name": "zones", "method": "watershed_zones"}
        ],
        "dem_filename": PARAMS["ex03"]["dem_filename"]
    },
    "ex09": {
        "modules": [
            {"name": "hydrography", "method": "add_hydrography",
             "args": [('types_obs', ['botopage2024_naizin_streams_perennial-intermittent']),
                      ('fields_obs', ['FID'])]},
            {"name": "subbasins", "method": "add_subbasin",
             "args": [('sub_snap_dist', 50)]}
        ],
        "visualizations": [
            {"name": "local", "method": "watershed_local",
             "dem_param": True},
            {"name": "dem", "method": "watershed_dem"},
            {"name": "zones", "method": "watershed_zones"}
        ],
        "dem_filename": PARAMS["ex09"]["dem_filename"]
    }
}

#configuration de la fonction paremtrization
PARAM_CONFIG = {
    "ex03": {
        "check_model": {"plot_cross": True, "check_grid": True},
        "climatic": {
            "recharge_from_params": True,  # Utilise p["recharge_monthly"]
            "runoff": None
        },
        "hydraulic_specific": {
            "update_bottom": True,
            "update_thick": True,
            "update_sy_simple": True,  # Un seul sy sans decay
            "decay_config": False
        },
        "particle_tracking": True
    },
    "ex09": {
        "check_model": {"plot_cross": False, "check_grid": False},
        "climatic": {
            "recharge_from_results": True,  # Utilise results['R_mm_day']
            "runoff_factor": 0.1
        },
        "hydraulic_specific": {
            "update_ss": True,
            "update_vka": True,
            "update_vertical": True,
            "update_decay": True,
            "sy_complex": True  # Sy avec decay
        },
        "particle_tracking": False
    }
}

MODELING_CONFIG = {
    "ex03": {
        "type": "multiple",
        "preprocessing": {"for_calib": False},
        "processing": {
            "write_model": True,
            "run_model": True,
            "link_mt3dms": False
        },
        "postprocessing_modflow": {
            "watertable_elevation": True,
            "watertable_depth": True,
            "seepage_areas": True,
            "outflow_drain": True,
            "groundwater_flux": True,
            "groundwater_storage": True,
            "accumulation_flux": True
        },
        "postprocessing_timeseries": {
            "datetime_format": False,
            "subbasin_results": True
        },
        "postprocessing_netcdf": True
    },
    "ex09": {
        "type": "single",
        "preprocessing": {"for_calib": True},
        "processing": {
            "write_model": True,
            "run_model": True,
            "link_mt3dms": True
        },
        "postprocessing_modflow": {
            "watertable_elevation": True,
            "watertable_depth": True,
            "seepage_areas": True,
            "outflow_drain": True,
            "groundwater_flux": False,
            "groundwater_storage": False,
            "accumulation_flux": True,
            "intermittency_weekly": True
        },
        "postprocessing_timeseries": {
            "datetime_format": True,
            "subbasin_results": True,
            "intermittency_weekly": True
        },
        "postprocessing_netcdf": False,
        "check_model": {
            "plot_cross": True,
            "check_grid": True,
            "cross_ylim": [0, 200]
        }
    }
}

# ============================================================================
# FONCTIONS HELPER
# ============================================================================

def select_period(df, first, last):
    """Sélectionne période dans dataframe par année"""
    return df[(df.index.year >= first) & (df.index.year <= last)]


# ============================================================================
# GENERIC METHODS - MODFLOW, MODPATH, MT3DMS (REUSABLE FOR ALL EXAMPLES)
# ============================================================================
# GENERIC MODELING METHODS - Imported from hydromodpy.modeling_workflow
# ============================================================================
# modflow(), modpath(), mt3dms() are now imported from modeling_workflow module
# See hydromodpy/modeling_workflow.py for implementations


# ============================================================================
# FONCTIONS COMMUNES (GÉNÉRIQUES - Utiliser directement)
# ============================================================================

def watershed(example_key):
    """Crée bassin versant - FONCTION GÉNÉRIQUE pour ex03 ou ex09"""
    example_names = {"ex03": "EXEMPLE 03", "ex09": "EXEMPLE 09"}
    print("\n" + "="*70)
    print(f"{example_names.get(example_key, example_key)} - WATERSHED".center(70))
    print("="*70)

    try:
        p = PARAMS[example_key]
        example_path = os.path.join(root_dir, p["base_path"])
        data_path = os.path.join(example_path, "data")
        out_path = os.path.join(root_dir, "examples", "results")
        dem_path = os.path.join(data_path, p["dem_filename"])

        if not os.path.exists(dem_path):
            print(f"DEM not found: {dem_path}\n")
            return None

        print(f"\nDEM: {dem_path}")

        # NEW API: Create Initializing and Geographic objects
        dem_coords = p["dem_coordinates"]  # [x, y, snap_dist, buffer, crs]

        # Create InitializingConfig object with required fields
        config = InitializingConfig(
            catch_name=p["watershed_name"],
            out_dir_path=Path(out_path),
            data_path=Path(data_path)
        )

        # Pass config object to Initializing
        initializing_object = initializing.Initializing(config)

        # Create GeographicConfig object
        geo_config = GeographicConfig(
            catch_def='from_outlet_coord',
            dem_init_path=Path(dem_path),
            x_outlet=dem_coords[0],
            y_outlet=dem_coords[1],
            snap_dist=dem_coords[2],
            buff_area=dem_coords[3],
            polyg_shp_path=None,
            dem_correc_type='breach'
        )

        # Create Geographic object with config and initializing_object
        geographic_object = geographic.Geographic(
            config=geo_config,
            initializing_object=initializing_object
        )

        BV = watershed_root.Watershed(
            load=False,
            initializing_object=initializing_object,
            geographic_object=geographic_object,
            save_object=True
        )

        stable_folder = initializing_object.stable_folder
        simulations_folder = initializing_object.simulations_folder
        calibration_folder = initializing_object.calibration_folder

        # IMPORTANT: Assign calibration_folder to BV (required for modpath preprocessing)
        BV.calibration_folder = calibration_folder

        print("Watershed extracted\n")
        return {
            'BV': BV, 'example_path': example_path, 'data_path': data_path,
            'out_path': out_path, 'stable_folder': stable_folder,
            'simulations_folder': simulations_folder, 'calibration_folder': calibration_folder
        }
    except Exception as e:
        print(f"Error: {e}\n")
        import traceback
        traceback.print_exc()
        return None


def recharge(results, example_key):
    """Ajoute recharge et runoff - FONCTION GÉNÉRIQUE pour ex03 ou ex09"""
    example_names = {"ex03": "EXEMPLE 03", "ex09": "EXEMPLE 09"}
    print("\n" + "="*70)
    print(f"{example_names.get(example_key, example_key)} - RECHARGE (CASES)".center(70))
    print("="*70)

    if not results:
        return None

    try:
        p = PARAMS[example_key]
        BV = results['BV']
        data_path = results['data_path']

        print("\n Add climatic...")
        BV.add_climatic()

        print("Update recharge (REANALYSIS)...")
        BV.climatic.update_recharge_reanalysis(
            path_file=os.path.join(data_path, '_climate_REANALYSIS.csv'),
            clim_mod='REA',
            clim_sce='historic',
            first_year=p["recharge_first_year"],
            last_year=p["recharge_last_year"],
            time_step=p["recharge_time_step"],
            sim_state='transient'
        )

        print("Update runoff (REANALYSIS)...")
        BV.climatic.update_runoff_reanalysis(
            path_file=os.path.join(data_path, '_climate_REANALYSIS.csv'),
            clim_mod='REA',
            clim_sce='historic',
            first_year=p["recharge_first_year"],
            last_year=p["recharge_last_year"],
            time_step=p["recharge_time_step"],
            sim_state='transient'
        )

        print("Recharge and runoff loaded\n")

        # Ajoute les data de recharge et runoff aux results pour utilisation en parametrization
        results['R_mm_day'] = BV.climatic.recharge
        results['runoff'] = BV.climatic.runoff
        results['climatic'] = BV.climatic

        return results
    except Exception as e:
        print(f"✗ Error: {e}\n")
        return results

def data(results):
    """DATA - Add geographic data to BV based on example key"""
    print("\n" + "="*70)
    print("DATA - Geographic Data Integration".center(70))
    print("="*70)

    if not results:
        return None

    try:
        BV = results['BV']
        data_path = results['data_path']

        # L'exemple est déterminé automatiquement
        example_key = results.get('example_key', CONFIG["example"])

        if example_key not in DATA_CONFIGS:
            print(f"No data configuration for {example_key}")
            return results

        config = DATA_CONFIGS[example_key]
        print(f"\nAdding data for {example_key.upper()}...")

        # Ajout des modules
        for module in config.get("modules", []):
            method_name = module["method"]
            if hasattr(BV, method_name):
                print(f"    • Adding {module['name']}...")

                # Prépare les arguments
                args = [data_path]  # First arg is always data_path
                kwargs = {}

                # Extraction des arguments optionnels
                if "args" in module:
                    for arg_name, arg_value in module["args"]:
                        kwargs[arg_name] = arg_value

                # Exécute la méthode avec data_path + kwargs
                try:
                    getattr(BV, method_name)(*args, **kwargs)
                except Exception as e:
                    print(f"    ⚠ Error adding {module['name']}: {e}")

        # Visualisations
        viz_list = config.get("visualizations", [])
        if viz_list:
            print("\n Creating watershed visualizations...")
            for viz in viz_list:
                try:
                    method_name = viz["method"]
                    if hasattr(visualization_watershed, method_name):
                        # Check if this visualization requires DEM path
                        if viz.get("dem_param"):
                            dem_filename = config.get("dem_filename")
                            if dem_filename:
                                dem_path = os.path.join(data_path, dem_filename)
                                if os.path.exists(dem_path):
                                    print(f"Creating {viz['name']}...")
                                    getattr(visualization_watershed, method_name)(dem_path, BV)
                                else:
                                    print(f"DEM file not found: {dem_path}")
                            else:
                                print(f"dem_filename not configured for {method_name}")
                        else:
                            print(f"Creating {viz['name']}...")
                            getattr(visualization_watershed, method_name)(BV)
                except Exception as e:
                    print(f"Error creating {viz['name']}: {e}")

        print("Data integration completed\n")
        return results

    except Exception as e:
        print(f"Error: {e}\n")
        return results


def parametrization(results):
    """PARAMETRIZATION - Configure hydraulic parameters based on example"""
    print("\n" + "="*70)
    example_key = results.get('example_key', CONFIG["example"])
    print(f"EXEMPLE {example_key.upper()} - PARAMETRIZATION".center(70))
    print("="*70)

    if not results:
        return None

    try:
        BV = results['BV']
        p = PARAMS[example_key]
        config = PARAM_CONFIG[example_key]

        # ÉTAPES COMMUNES
        print("\n Import modules...")
        BV.add_settings()
        BV.add_climatic()
        BV.add_hydraulic()

        print(" Update frame settings...")
        BV.settings.update_box_model(p["box"])
        BV.settings.update_sink_fill(p["sink_fill"])
        BV.settings.update_simulation_state(p["sim_state"])

        # Always set check_model parameters (needed by preprocessing_modflow)
        plot_cross = config["check_model"].get("plot_cross", False)
        check_grid = config["check_model"].get("check_grid", False)
        cross_ylim = config["check_model"].get("cross_ylim", [0, 150])

        BV.settings.update_check_model(
            plot_cross=plot_cross,
            check_grid=check_grid,
            cross_ylim=cross_ylim
        )

        print(" Update boundary...")
        BV.settings.update_bc_sides(p["bc_left"], p["bc_right"])
        BV.settings.update_dis_perlen(dis_perlen=p["dis_perlen"])
        BV.add_oceanic(p["sea_level"])

        print(" Update hydraulic base...")
        BV.hydraulic.update_nlay(p["nlay"])
        BV.hydraulic.update_cond_drain(p["cond_drain"])
        BV.hydraulic.update_lay_decay(p["lay_decay"])
        BV.hydraulic.update_bottom(p["bottom"])

        # CLIMATIC
        print(" Setup climatic...")
        BV.climatic.update_first_clim('mean')

        if config["climatic"].get("recharge_from_params"):
            recharge = pd.Series(p["recharge_monthly"]) / 30 / 1000
            BV.climatic.update_recharge(recharge, sim_state=p["sim_state"])

        elif config["climatic"].get("recharge_from_results"):
            R_mm_day = results.get('R_mm_day')
            if R_mm_day is not None:
                recharge = R_mm_day[:] / 1000
            else:
                recharge = pd.Series([0.1] * 365) / 1000
            BV.climatic.update_recharge(recharge, sim_state=p["sim_state"])

            if config["climatic"].get("runoff_factor"):
                runoff = recharge * config["climatic"]["runoff_factor"]
                BV.climatic.update_runoff(runoff, sim_state=p["sim_state"])

        # HYDRAULIC SPECIFIQUE
        print(" Update hydraulic specific...")

        if config["hydraulic_specific"].get("update_thick"):
            BV.hydraulic.update_thick(p.get("thick", p.get("thickness")))

        if config["hydraulic_specific"].get("update_sy_simple"):
            BV.hydraulic.update_sy(p["sy"])

        if config["hydraulic_specific"].get("update_ss"):
            BV.hydraulic.update_ss(p["ss"])

        if config["hydraulic_specific"].get("update_vka"):
            BV.hydraulic.update_vka(p["vka"])

        if config["hydraulic_specific"].get("update_vertical"):
            BV.hydraulic.update_hk_vertical(p["verti_hk"])
            BV.hydraulic.update_sy_vertical(p["verti_sy"])
            BV.hydraulic.update_ss_vertical(p["verti_ss"])

        if config["hydraulic_specific"].get("update_decay"):
            BV.hydraulic.update_sy_decay(p["sy_decay"])
            BV.hydraulic.update_ss_decay(p["ss_decay"])

        if config["hydraulic_specific"].get("sy_complex"):
            BV.hydraulic.update_hk(p["the_K0"])
            BV.hydraulic.update_hk_decay(
                1 / p["alpha"],
                min_value=p["Kmin_for_hk_decay"],
                log_transf=p["Klog_transf"],
                grad_elev=[93, 136, -20]
            )

            BV.hydraulic.update_sy(p["the_sy0"])
            BV.hydraulic.update_sy_decay(
                (1 / p["alpha"]) / p["n_factor"],
                min_value=p["Symin_for_sy_decay"],
                log_transf=p["Klog_transf"],
                grad_elev=[93, 136, -20]
            )

            BV.hydraulic.update_ss(p["the_ss0"])
            BV.hydraulic.update_ss_decay(0)

        # PARTICLE TRACKING
        if config.get("particle_tracking"):
            print(" Update particle tracking...")
            BV.settings.update_input_particles(
                zone_partic=BV.geographic.watershed_box_buff_dem
            )

        print("Parametrization completed\n")
        return results

    except Exception as e:
        print(f"Error: {e}\n")
        import traceback
        traceback.print_exc()
        return results

def modeling(results):
    """MODELING - Run MODFLOW using generic workflow function"""
    print("\n" + "="*70)
    example_key = results.get('example_key', CONFIG["example"])
    print(f"EXEMPLE {example_key.upper()} - MODELING".center(70))
    print("="*70)

    if not results:
        return None

    try:
        BV = results['BV']
        p = PARAMS[example_key]
        config = MODELING_CONFIG[example_key]

        print(f"\n  Running MODFLOW for {example_key}...")

        list_model_name = []
        list_success_modflow = []
        list_model_modflow = []

        # Détermine les valeurs de conductivité hydraulique et appelle la fonction générique
        if config["type"] == "multiple":
            hk_values = [h * 24 * 3600 for h in p["list_hyd_cond"]]
            base_name = p["iD_set_simulations"]
            model_names = [f"{base_name}_{round(h, 3)}" for h in hk_values]
            folder = results['simulations_folder']
            save_file = os.path.join(folder, f'results_listing_{base_name}.pkl')
        else:  # single
            hk_values = [p["the_K0"]]
            the_K0 = p["the_K0"] / 24 / 3600
            model_names = [f"{p['vers']}_K{the_K0:.1e}_a{p['alpha']:.1f}_Sy{p['the_sy0']*100:.1f}"]
            folder = results['calibration_folder']

        # Exécute chaque modèle via fonction générique modflow()
        for i, (hk_value, model_name) in enumerate(zip(hk_values, model_names)):
            print(f"    Model {i+1}/{len(hk_values)}: {model_name}")

            result = modflow(BV, model_name, hk_value, config)
            list_model_name.append(result['model_name'])
            list_success_modflow.append(result['success'])
            list_model_modflow.append(result['model_modflow'])

        # Sauvegarde pickle
        dictio = {
            'list_model_name': list_model_name,
            'list_success_modflow': list_success_modflow
        }
        import os
        os.makedirs(os.path.dirname(save_file) if os.path.dirname(save_file) else '.', exist_ok=True)
        with open(save_file, 'wb') as f:
            pickle.dump(dictio, f)

        # Met à jour results
        if config["type"] == "multiple":
            results['list_model_name'] = list_model_name
            results['list_success_modflow'] = list_success_modflow
            results['list_model_modflow'] = list_model_modflow
            results['iD_set_simulations'] = p.get("iD_set_simulations", "")
            if list_model_name:
                results['model_name'] = list_model_name[0]
                results['model_modflow'] = list_model_modflow[0]
                results['success_modflow'] = list_success_modflow[0]
        else:
            results['model_name'] = list_model_name[0] if list_model_name else None
            results['model_modflow'] = list_model_modflow[0] if list_model_modflow else None
            results['success_modflow'] = list_success_modflow[0] if list_success_modflow else None

        results['BV'] = BV
        print("  ✓ MODFLOW modeling completed\n")
        return results

    except Exception as e:
        print(f"Error: {e}\n")
        import traceback
        traceback.print_exc()
        return results


# ============================================================================
# SPECIALIZED METHODS - EX03, EX09 (USES GENERIC METHODS)
# ============================================================================

def modflow_ex03(BV, results, config):
    """EXAMPLE 03 - MODFLOW with multiple HK values (calls generic modflow())"""
    print("\n MODFLOW: Creating multiple models...")

    p = PARAMS["ex03"]
    list_model_name = []
    list_success_modflow = []
    list_model_modflow = []

    hk_values = [h * 24 * 3600 for h in p["list_hyd_cond"]]
    base_name = p["iD_set_simulations"]

    for hk_value in hk_values:
        model_name = base_name + '_' + str(round(hk_value, 3))
        result = modflow(BV, model_name, hk_value, config)
        list_model_name.append(model_name)
        list_model_modflow.append(result['model_modflow'])
        list_success_modflow.append(result['success'])

    dictio = {'list_model_name': list_model_name, 'list_success_modflow': list_success_modflow}
    pickle_file = os.path.join(results['simulations_folder'], f'results_listing_{base_name}.pkl')
    with open(pickle_file, 'wb') as f:
        pickle.dump(dictio, f)

    results['list_model_name'] = list_model_name
    results['list_success_modflow'] = list_success_modflow
    results['list_model_modflow'] = list_model_modflow
    if list_model_name:
        results['model_name'] = list_model_name[0]
        results['model_modflow'] = list_model_modflow[0]
        results['success_modflow'] = list_success_modflow[0]

    print("MODFLOW models created\n")
    return results


def modflow_ex09(BV, results, config):
    """EXAMPLE 09 - MODFLOW single model (calls generic modflow())"""
    print("\n MODFLOW: Creating single calibration model...")

    p = PARAMS["ex09"]
    the_K0_ms = p["the_K0"] / 24 / 3600
    model_name = f"{p['vers']}_K{the_K0_ms:.1e}_a{p['alpha']:.1f}_Sy{p['the_sy0']*100:.1f}"

    result = modflow(BV, model_name, p["the_K0"], config)

    results['model_name'] = model_name
    results['model_modflow'] = result['model_modflow']
    results['success_modflow'] = result['success']
    results['vers'] = p['vers']

    print("MODFLOW model created\n")
    return results


def modpath_ex09(results):
    """EXAMPLE 09 - MODPATH (calls generic modpath())"""
    print("\n" + "="*70)
    print("EXEMPLE 09 - MODPATH (PARTICLE TRACKING)".center(70))
    print("="*70)

    BV = results.get('BV')
    modpath_result = modpath(BV, results, for_calib=True)

    results['model_modpath'] = modpath_result['model_modpath']
    results['success_modpath'] = modpath_result['success']
    results['BV'] = modpath_result['BV']

    print("MODPATH completed\n")
    return results


def mt3dms_ex09(results):
    """EXAMPLE 09 - MT3DMS (calls generic mt3dms())"""
    print("\n" + "="*70)
    print("EXEMPLE 09 - MT3DMS (TRANSPORT MODEL)".center(70))
    print("="*70)

    try:
        BV = results.get('BV')
        model_modflow = results.get('model_modflow')
        p = PARAMS["ex09"]
        scenario = 's1'

        if BV is None or model_modflow is None:
            print("✗ BV or model_modflow not found\n")
            results['success_mt3dms'] = False
            return results

        # Setup transport parameters (like example_09.py)
        print("  • Configuring transport parameters...")
        BV.add_transport()

        nper = model_modflow.nper
        nlay = model_modflow.mf.nlay
        nrow = model_modflow.mf.nrow
        ncol = model_modflow.mf.ncol

        sconc_init = np.ones((nlay, nrow, ncol)) * (p["sconc_init_value"] / 1000)
        sconc_input = {i: np.ones((nrow, ncol)) * (p["sconc_input_value"] / 1000) for i in range(nper)}
        sconc_input = dict(islice(sconc_input.items(), 1, None))
        rate_decay = np.ones((nlay, nrow, ncol)) * p["rate_decay_value"]

        BV.transport.update_mt3dms_parameters(
            spc_name=p["spc_name"],
            sconc_init=sconc_init,
            sconc_input=sconc_input,
            disp_long=p["disp_long"],
            disp_transh=p["disp_transh"],
            disp_transv=p["disp_transv"],
            diffu_coeff=p["diffu_coeff"],
            react_order=p["react_order"],
            rate_decay=rate_decay,
            plot_conc=p["plot_conc"]
        )

        # Call generic mt3dms with transport object
        mt3dms_result = mt3dms(BV, results, scenario=scenario, for_calib=True, transport=BV.transport)

        results['model_mt3dms'] = mt3dms_result['model_mt3dms']
        results['success_mt3dms'] = mt3dms_result['success']
        results['BV'] = mt3dms_result['BV']
        results['scenario'] = scenario

        print("MT3DMS completed\n")
        return results

    except Exception as e:
        print(f"✗ MT3DMS error: {e}\n")
        import traceback
        traceback.print_exc()
        results['success_mt3dms'] = False
        return results

# ============================================================================
# EXEMPLE 03 - HYDROGRAPHIC NETWORK (FONCTIONS SPÉCIFIQUES)
# ============================================================================



def ex03_recharge_plot(results):
    """EXEMPLE 03 - RECHARGE avec plot spécifique"""

    if not results:
        return None

    try:
        print("\n Create plot (specific to Ex03)...")
        BV = results['BV']

        fig, ax = plt.subplots(1, 1, figsize=(6, 3))
        R = BV.climatic.recharge.resample('YE').sum()
        r = BV.climatic.runoff.resample('YE').sum()
        ax.plot(R, label='recharge_reanalysis', c='dodgerblue', lw=2)
        ax.plot(r, label='runoff_reanalysis', c='navy', lw=2)
        ax.set_xlabel('Date')
        ax.set_ylabel('[mm/year]')
        ax.legend()
        plt.tight_layout()

        if CONFIG.get('display_figures', True):
            plt.show()
        plt.close(fig)

        print("Recharge calculated\n")
        return results
    except Exception as e:
        print(f" Error: {e}\n")
        return results

def ex03_modeling(results):
    """EXEMPLE 03 - MODELING: MODFLOW + RELOAD + POSTPROCESSING"""
    print("\n" + "="*70)
    print("EXEMPLE 03 - MODELING".center(70))
    print("="*70)

    if not results:
        return None

    try:
        p = PARAMS["ex03"]
        BV = results['BV']
        simulations_folder = results['simulations_folder']
        out_path = results['out_path']

        print("\n  MODFLOW: create and run models...")
        iD_set_simulations = p["iD_set_simulations"]
        config = MODELING_CONFIG["ex03"]
        list_model_name = []
        list_success_modflow = []
        list_model_modflow = []

        for hyd_cond in p["list_hyd_cond"]:
            hyd_cond_day = hyd_cond * 24 * 3600
            model_name = iD_set_simulations + '_' + str(round(hyd_cond_day, 3))

            # Use generic modflow function from modeling_workflow
            result = modflow(BV, model_name, hyd_cond_day, config)

            list_model_name.append(result['model_name'])
            list_success_modflow.append(result['success'])
            list_model_modflow.append(result['model_modflow'])

        print(" Save results...")
        dictio = {
            'list_model_name': list_model_name,
            'list_success_modflow': list_success_modflow,
            'list_model_modflow': list_model_modflow
        }
        pickle_file = os.path.join(simulations_folder, 'results_listing_' + iD_set_simulations + '.pkl')
        with open(pickle_file, 'wb') as f:
            pickle.dump(dictio, f)

        # Postprocessing is already handled by the generic modflow() function
        # No additional postprocessing needed here

        results['list_model_name'] = list_model_name
        results['list_success_modflow'] = list_success_modflow
        results['list_model_modflow'] = list_model_modflow
        results['iD_set_simulations'] = iD_set_simulations

        # Add single model refs for compatibility with rest of pipeline (for ex03, use first model)
        if list_model_name:
            results['model_name'] = list_model_name[0]
            results['model_modflow'] = list_model_modflow[0]
            results['success_modflow'] = list_success_modflow[0]

        print("Modeling completed\n")
        return results
    except Exception as e:
        print(f"Error: {e}\n")
        return results


def ex03_plot(results):
    """EXEMPLE 03 - PLOT: CROSS, MAP, GRAPH (Watershed visualizations done in data()"""
    print("\n" + "="*70)
    print("EXEMPLE 03 - PLOT (CROSS, MAP, GRAPH)".center(70))
    print("="*70)

    if not results:
        return None

    try:
        BV = results['BV']
        out_path = results['out_path']
        simulations_folder = results['simulations_folder']
        stable_folder = results['stable_folder']
        watershed_name = PARAMS["ex03"]["watershed_name"]

        print("\n  • Create MODFLOW visualization plots...")

        list_model_name = results.get('list_model_name', [])
        list_success_modflow = results.get('list_success_modflow', [])
        list_model_modflow = results.get('list_model_modflow', [])

        if not list_model_name:
            print("No MODFLOW models to plot\n")
            return results

        print("\n Create CROSS section plots...")
        for i, (model_name, success, model) in enumerate(zip(list_model_name,
                                                              list_success_modflow,
                                                              list_model_modflow)):
            fig, ax = plt.subplots(1, 1, figsize=(5, 3), dpi=300)

            dem_data = imageio.imread(BV.geographic.watershed_dem)
            dem_data = np.ma.masked_where(dem_data < 0, dem_data)

            wt_file = os.path.join(
                simulations_folder, model_name,
                '_postprocess/_rasters/watertable_elevation_t(0).tif'
            )
            if os.path.exists(wt_file):
                wt_data = imageio.imread(wt_file)
                wt_data = np.ma.masked_where(wt_data < 0, wt_data)
                wt_v_plot = wt_data.astype(float)[:, int(dem_data.shape[1]/2)]
            else:
                wt_v_plot = dem_data.astype(float)[:, int(dem_data.shape[1]/2)]

            dem_v_plot = dem_data.astype(float)[:, int(dem_data.shape[1]/2)]
            dem_v_plot[dem_v_plot < 0] = np.nan

            ax.fill_between(np.arange(len(dem_v_plot)) * 75, dem_v_plot - 30, wt_v_plot,
                           color='dodgerblue', alpha=0.5, lw=0)
            ax.plot(np.arange(len(wt_v_plot)) * 75, wt_v_plot, color='navy', lw=1)
            ax.fill_between(np.arange(len(dem_v_plot)) * 75, wt_v_plot, dem_v_plot,
                           color='saddlebrown', alpha=0.5, lw=0)
            ax.plot(np.arange(len(dem_v_plot)) * 75, dem_v_plot, 'saddlebrown', lw=1.5)
            ax.fill_between(np.arange(len(dem_v_plot)) * 75, 0, dem_v_plot - 30,
                           color='lightgrey', alpha=1, lw=0, zorder=10)

            ax.set_xlim(1000, 4000)
            ax.set_ylim(85, 130)
            ax.set_xlabel('Distance [m]')
            ax.set_ylabel('Elevation [m]')
            ax.set_title(f'K = {model.hk.mean()/24/3600:.2e} m/s')

            # Save figure
            figures_dir = os.path.join(stable_folder, '_figures')
            toolbox.create_folder(figures_dir)
            fig.savefig(os.path.join(figures_dir, f'cross_{i:02d}_{model_name}.png'), dpi=300, bbox_inches='tight')

            if CONFIG.get('display_figures', True):
                plt.show()
            plt.close(fig)

        print("Create MAP plots...")
        for model_name, success, model in zip(list_model_name,
                                              list_success_modflow,
                                              list_model_modflow):
            fig, ax = plt.subplots(1, 1, figsize=(5, 3), dpi=300)

            dem_data = imageio.imread(BV.geographic.watershed_box_buff_dem)
            dem_data = np.ma.masked_where(dem_data < 0, dem_data)

            ax.imshow(dem_data, alpha=0.5, cmap='Greys')

            seep_file = os.path.join(
                simulations_folder, model_name,
                '_postprocess/_rasters/seepage_areas_t(0).tif'
            )
            if os.path.exists(seep_file):
                seep_data = imageio.imread(seep_file)
                seep_data = np.ma.masked_where(seep_data <= 0, seep_data)
                ax.imshow(seep_data, cmap=mpl.colors.ListedColormap('darkorange'), alpha=0.7)

            ax.set_xlabel('X [pixels]')
            ax.set_ylabel('Y [pixels]')
            ax.set_title(f'K = {model.hk.mean()/24/3600:.2e} m/s')

            # Save figure
            figures_dir = os.path.join(stable_folder, '_figures')
            toolbox.create_folder(figures_dir)
            fig.savefig(os.path.join(figures_dir, f'map_{list_model_name.index(model_name):02d}_{model_name}.png'), dpi=300, bbox_inches='tight')

            if CONFIG.get('display_figures', True):
                plt.show()
            plt.close(fig)

        print("Create GRAPH plots...")
        fig, ax = plt.subplots(1, 1, figsize=(5, 4), dpi=300)

        for model_name in list_model_name:
            csv_file = os.path.join(
                simulations_folder, model_name,
                '_postprocess/_timeseries/_simulated_timeseries.csv'
            )
            if os.path.exists(csv_file):
                simul_csv = pd.read_csv(csv_file, sep=';')
                model_idx = list_model_name.index(model_name)
                if model_idx < len(list_model_modflow):
                    model = list_model_modflow[model_idx]
                    ax.plot(model.hk.mean() / 24 / 3600,
                           simul_csv['seepage_areas'].mean(),
                           marker='o', ms=8, lw=0, color='k')

        ax.set_xscale('log')
        ax.set_xlabel('K [m/s]')
        ax.set_ylabel('Drainage density [%]')

        # Save figure
        figures_dir = os.path.join(stable_folder, '_figures')
        toolbox.create_folder(figures_dir)
        fig.savefig(os.path.join(figures_dir, 'graph_drainage_density.png'), dpi=300, bbox_inches='tight')

        if CONFIG.get('display_figures', True):
            plt.show()
        plt.close(fig)

        # Create 2D visualization maps
        print("Create 2D visualization maps...")
        visu = visualization_results.Visualization(BV, list_model_name[0] if list_model_name else 'model')
        try:
            visu.visual2D(object_list=[
                'map',
                'grid',
                'watertable',
                'watertable_depth',
                'drain_flow',
                'accumulation'
            ],
            color_scale=[
                (None, None),
                (80, 150),
                (80, 150),
                (0, 10),
                (0, 200),
                (0, 30000)
            ],
            lines=1000)
            print("2D visualization maps created")
        except Exception as e:
            print(f" Warning: Could not create 2D visualizations: {e}")

        print("Plots completed\n")
        return results
    except Exception as e:
        print(f" Error: {e}\n")
        return results


# ============================================================================
# EXEMPLE 09 - MATCHING STREAMS CLASS
# ============================================================================

class MatchingStreams:
    """
    Class for the calibration based on river occurency

    Attributes
    ----------
    watershed : HydroModPy Watershed object
    iteration_label : str, model name for calibration
    from_calib : bool, whether to use calibration or simulations folder

    Methods
    -------
    prepare_files() : setup GIS files for stream comparison
    sim_to_obs() : distance from simulated to observed streams
    obs_to_sim() : distance from observed to simulated streams
    """

    def __init__(self, watershed, iteration_label=None, from_calib=True):
        self.geographic = watershed.geographic
        self.hydrography = watershed.hydrography
        if from_calib:
            self.calibration_folder = watershed.calibration_folder
        else:
            self.calibration_folder = watershed.simulations_folder
        self.iteration_label = iteration_label

        self.watershed_shp = watershed.geographic.watershed_shp
        self.watershed_fill = watershed.geographic.watershed_fill
        self.watershed_direc = watershed.geographic.watershed_direc

        self.prepare_files()
        self.sim_to_obs()
        self.obs_to_sim()

    def prepare_files(self):
        """Prepare GIS files for whitebox analysis"""
        self.results_folder = os.path.join(self.calibration_folder, self.iteration_label, '_postprocess')
        toolbox.create_folder(self.results_folder)
        self.dichotomy_folder = os.path.join(self.calibration_folder, self.iteration_label, '_matchingstreams')
        toolbox.create_folder(self.dichotomy_folder)

        # Observed streams
        self.buff_tif_obs = self.hydrography.tif_streams
        self.tif_obs = os.path.join(self.dichotomy_folder, 'obs.tif')
        toolbox.clip_tif(self.buff_tif_obs, self.watershed_shp, self.tif_obs, False)
        self.pt_obs = os.path.join(self.dichotomy_folder, 'obs_pt.shp')
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obs)
        self.pt_obsf = os.path.join(self.dichotomy_folder, 'obs_ptf.shp')
        wbt.raster_to_vector_points(self.tif_obs, self.pt_obsf)
        self.obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.tif')
        wbt.trace_downslope_flowpaths(self.pt_obs, self.watershed_direc, self.obs_flow)

        # Simulated streams
        tif_sim = os.path.join(self.results_folder, '_rasters', 'seepage_areas_t(0).tif')
        self.tif_sim = os.path.join(self.dichotomy_folder, 'sim.tif')
        toolbox.clip_tif(tif_sim, self.watershed_shp, self.tif_sim, False)
        self.pt_sim = os.path.join(self.dichotomy_folder, 'sim_pt.shp')
        wbt.raster_to_vector_points(self.tif_sim, self.pt_sim)
        self.pt_simf = os.path.join(self.dichotomy_folder, 'sim_ptf.shp')
        wbt.raster_to_vector_points(self.tif_sim, self.pt_simf)
        self.sim_flow = os.path.join(self.dichotomy_folder, 'simflow.tif')
        wbt.trace_downslope_flowpaths(self.pt_sim, self.watershed_direc, self.sim_flow)

    def sim_to_obs(self):
        """Calculate distance from simulated streams to observed"""
        self.pt_sim_flow = os.path.join(self.dichotomy_folder, 'simflow.shp')
        wbt.raster_to_vector_points(self.sim_flow, self.pt_sim_flow)
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

    def obs_to_sim(self):
        """Calculate distance from observed streams to simulated"""
        self.pt_obs_flow = os.path.join(self.dichotomy_folder, 'obsflow.shp')
        wbt.raster_to_vector_points(self.obs_flow, self.pt_obs_flow)
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


# ============================================================================
# EXEMPLE 09 - ADVANCED FUNCTIONS (MODPATH, MT3DMS, ANIMATIONS)
# ============================================================================

def ex09_matching_streams(results):
    """EXEMPLE 09 - MATCHING STREAMS: Calibration by stream occurrence"""
    print("\n" + "="*70)
    print("EXEMPLE 09 - MATCHING STREAMS".center(70))
    print("="*70)

    if not results:
        return None

    try:
        BV = results.get('BV')
        model_name = results.get('model_name')

        if BV is None or model_name is None:
            print(" BV or model_name not found\n")
            return results

        print(f"\n  • Initialize MatchingStreams for {model_name}...")
        matching = MatchingStreams(BV, iteration_label=model_name, from_calib=True)

        results['matching_streams'] = matching
        print("Matching streams analysis completed\n")
        return results
    except Exception as e:
        print(f" Error: {e}\n")
        import traceback
        traceback.print_exc()
        return results


def ex09_modpath(results):
    """EXEMPLE 09 - MODPATH: Particle tracking and residence times"""
    print("\n" + "="*70)
    print("EXEMPLE 09 - MODPATH (PARTICLE TRACKING)".center(70))
    print("="*70)

    if not results:
        return None

    try:
        BV = results.get('BV')
        model_modflow = results.get('model_modflow')
        model_name = results.get('model_name')

        if BV is None or model_modflow is None:
            print(" BV or model_modflow not found\n")
            results['success_modpath'] = False
            return results

        print(f"\n  Setup particle tracking for {model_name}...")

        # MODPATH setup using generic workflow
        modpath_result = modpath(BV, results, for_calib=True)

        results['model_modpath'] = modpath_result['model_modpath']
        results['success_modpath'] = modpath_result['success']
        results['BV'] = modpath_result['BV']

        print("MODPATH completed\n")
        return results
    except Exception as e:
        print(f"Error: {e}\n")
        import traceback
        traceback.print_exc()
        results['success_modpath'] = False
        return results


def ex09_mt3dms(results):
    """EXEMPLE 09 - MT3DMS: Contaminant transport with decay"""
    print("\n" + "="*70)
    print("EXEMPLE 09 - MT3DMS (TRANSPORT MODEL)".center(70))
    print("="*70)

    if not results:
        return None

    try:
        BV = results.get('BV')
        model_modflow = results.get('model_modflow')
        model_name = results.get('model_name')

        if BV is None or model_modflow is None:
            print("✗ BV or model_modflow not found\n")
            results['success_mt3dms'] = False
            return results

        # MT3DMS setup using generic workflow
        scenario = 's1'
        print(f"\n  • Setup MT3DMS transport for {model_name} - scenario {scenario}...")
        mt3dms_result = mt3dms(BV, results, scenario=scenario, for_calib=True)

        results['model_mt3dms'] = mt3dms_result['model_mt3dms']
        results['success_mt3dms'] = mt3dms_result['success']
        results['BV'] = mt3dms_result['BV']
        results['scenario'] = scenario

        # Timeseries postprocessing with configuration
        timeseries_config = {
            'suffix_name': scenario,
            'datetime_format': True,
            'subbasin_results': True,
            'intermittency_weekly': False,
            'intermittency_monthly': True,
            'residence_times': True,
            'concentration_seepage': True,
            'mass_accumulated': True
        }
        timeseries(BV, results, timeseries_config=timeseries_config)

        print("MT3DMS completed\n")
        return results

    except Exception as e:
        print(f"Error: {e}\n")
        import traceback
        traceback.print_exc()
        results['success_mt3dms'] = False
        return results


def ex09_plot_streamflow(results):
    """EXEMPLE 09 - PLOT STREAMFLOW: Match observed vs simulated"""
    print("\n  Create streamflow plots...")

    if not results:
        return results

    try:
        BV = results.get('BV')
        model_name = results.get('model_name')
        calibration_folder = results.get('calibration_folder')
        data_path = results['data_path']

        if BV is None:
            return results

        # Get watershed area - try catch_area first, fall back to area
        try:
            area = int(round(BV.geographic.catch_area))
        except AttributeError:
            try:
                area = int(round(BV.geographic.area))
            except AttributeError:
                print(" Could not determine catchment area, skipping streamflow plots")
                return results

        vers = PARAMS["ex09"]["vers"]

        # Read observed streamflow
        Qobs_path = os.path.join(data_path, 'Debit_Exu_Kervidy_Aghrys_LJr_2024-04.txt')
        if not os.path.exists(Qobs_path):
            print(f"Streamflow file not found: {Qobs_path}")
            return results

        Qobs = pd.read_csv(Qobs_path, sep=';', header=None)
        date = pd.to_datetime(Qobs[0] + ' ' + Qobs[1], format="%d/%m/%Y %H:%M:%S")
        Qobs.index = date
        Qobs = Qobs[2].to_frame(name="Q")
        Qobs = Qobs / 1000  # L/d to m3/d
        Qobs = (Qobs / (area * 1000000))  # m3/d to m/day
        Qobs = Qobs.resample('W').mean()
        Qobs = Qobs * 7 * 1000

        # Plot for each simulation
        simul_list = sorted(glob.glob(os.path.join(calibration_folder, vers + '*')), key=os.path.getmtime)

        for simul in simul_list[:]:
            fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]}, figsize=(12, 3.5), dpi=300)

            model_name_sim = os.path.basename(simul)
            Smod_path = os.path.join(simul, '_postprocess/_timeseries/_simulated_timeseries.csv')

            if not os.path.exists(Smod_path):
                continue

            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)

            Rmod = Smod['recharge'] * 7 * 1000
            rmod = Smod['runoff'] * 7 * 1000
            Omod = (Smod['outflow_drain'] * 7 * 1000)
            Qmod = Omod + rmod

            ax = a0
            ax.plot(Qobs, color='k', lw=2, ls='-', zorder=0, label='Observed')
            ax.plot(Qmod, color='red', lw=2, label='Simulated: outflow')
            ax.plot(Rmod, color='dodgerblue', lw=2, ls='-', zorder=0, label='Recharge')
            ax.set_xlabel('Date')
            ax.set_ylabel('Q / A [mm/week]')
            ax.xaxis.set_major_locator(mdates.YearLocator(1))
            ax.xaxis.set_minor_locator(mdates.MonthLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
            ax.set_xlim(pd.to_datetime('2002'), pd.to_datetime('2005'))
            ax.legend(loc='upper left')
            ax.set_title(model_name_sim.upper(), fontsize=10)
            ax.set_ylim(None, 50)

            ax = a1
            ax.text(0.5, 0.5, 'Scatter plot\n(Not implemented)',
                   ha='center', va='center', transform=ax.transAxes)
            ax.set_xlim(0.1, 300)
            ax.set_ylim(0.1, 300)
            fig.tight_layout()

            # Save figure
            figures_dir = os.path.join(calibration_folder, '_figures')
            toolbox.create_folder(figures_dir)
            fig.savefig(os.path.join(figures_dir, f'streamflow_{model_name_sim}.png'), dpi=300, bbox_inches='tight')

            if CONFIG.get('display_figures', True):
                plt.show()
            plt.close(fig)

        print("Streamflow plots created")
        return results

    except Exception as e:
        print(f" Error: {e}")
        return results


def ex09_plot_piezometry(results):
    """EXEMPLE 09 - PLOT PIEZOMETRY: Watertable depth evolution"""
    print("\n Create piezometry plots...")

    if not results:
        return results

    try:
        BV = results.get('BV')
        model_name = results.get('model_name')
        calibration_folder = results.get('calibration_folder')
        results_data = results.get('R_mm_day_filt')

        if BV is None or model_name is None:
            return results

        vers = PARAMS["ex09"]["vers"]
        simul_list = sorted(glob.glob(os.path.join(calibration_folder, vers + '*')), key=os.path.getmtime)

        for simul in simul_list[:]:
            model_name_sim = os.path.basename(simul)
            Smod_path = os.path.join(simul, '_postprocess/_timeseries/_simulated_timeseries.csv')

            if not os.path.exists(Smod_path):
                continue

            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)
            Rmod = Smod['recharge'] * 7 * 1000
            WTDmod = Smod['watertable_depth']

            fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]}, figsize=(12, 3.5), dpi=300)

            ax = a0
            ax.plot(WTDmod, marker='o', color='red', lw=2, label='Simulated: watertable depth')
            ax.set_xlabel('Date')
            ax.set_ylabel('WT depth [m]')
            ax.xaxis.set_major_locator(mdates.YearLocator(1))
            ax.xaxis.set_minor_locator(mdates.MonthLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
            ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
            ax.legend(loc='upper left')
            ax.set_title(model_name_sim.upper(), fontsize=10)
            ax.set_ylim(0, None)
            ax.invert_yaxis()

            axb = ax.twinx()
            if results_data is not None:
                axb.bar(results_data.index, results_data * 7, color='dodgerblue', width=10,
                       edgecolor='None', lw=0, alpha=0.5, label='Recharge')
                axb.set_ylim(0, 100)
                axb.invert_yaxis()

            fig.tight_layout()

            # Save figure
            figures_dir = os.path.join(calibration_folder, '_figures')
            toolbox.create_folder(figures_dir)
            fig.savefig(os.path.join(figures_dir, f'piezometry_{model_name_sim}.png'), dpi=300, bbox_inches='tight')

            if CONFIG.get('display_figures', True):
                plt.show()
            plt.close(fig)

        print(" Piezometry plots created")
        return results

    except Exception as e:
        print(f"Error: {e}")
        return results


def ex09_plot_pathlines(results):
    """EXEMPLE 09 - PLOT PATHLINES: Residence time visualization"""
    print("\n Create pathlines plots...")

    if not results:
        return results

    try:
        BV = results.get('BV')
        model_modpath = results.get('model_modpath')
        stable_folder = results.get('stable_folder')
        success_modpath = results.get('success_modpath', False)

        if not success_modpath:
            print(" MODPATH execution was not successful, skipping pathlines")
            return results

        if BV is None:
            print("BV not available")
            return results

        model_name = results.get('model_name')
        calibration_folder = results.get('calibration_folder')

        # Check if pathlines files exist
        shp_pathlines_path = os.path.join(calibration_folder, model_name, '_postprocess/_particles/pathlines_weighted.shp')
        shp_endpoints_path = os.path.join(calibration_folder, model_name, '_postprocess/_particles/starting_weighted.shp')

        if not os.path.exists(shp_pathlines_path):
            print(f"      ⚠ Pathlines shapefile not found: {shp_pathlines_path}")
            print(f"      ⚠ Skipping pathlines visualization")
            return results

        try:
            shp_pathlines = gpd.read_file(shp_pathlines_path)
            shp_endpoints = gpd.read_file(shp_endpoints_path)
        except Exception as e:
            print(f" Could not read shapefiles: {e}")
            return results

        # Check watershed shapefile exists
        watershed_shp_path = os.path.join(stable_folder, 'geographic', 'watershed.shp')
        if not os.path.exists(watershed_shp_path):
            print(f"Watershed shapefile not found: {watershed_shp_path}")
            return results

        line = gpd.read_file(watershed_shp_path)

        # Check DEM exists
        dem_path = BV.geographic.watershed_box_buff_dem
        if not os.path.exists(dem_path):
            print(f"      ⚠ DEM not found: {dem_path}")
            return results

        dem_rio = rasterio.open(dem_path)
        dem_data = dem_rio.read(1)
        dem_data = np.ma.masked_where(dem_data < 0, dem_data)

        # Get time column - try different names
        time_col = None
        for col_name in ['time_win_y', 'time', 'TIME', 'residence_time']:
            if col_name in shp_pathlines.columns:
                time_col = col_name
                break

        if time_col is None:
            print(f"No time column found in pathlines. Available: {shp_pathlines.columns.tolist()}")
            # Use a default visualization without time coloring
            time_col = None

        norm = mcolors.LogNorm(vmin=0.1, vmax=100) if time_col else None
        im = cm.ScalarMappable(cmap='jet', norm=norm) if time_col else None
        if im:
            im.set_array([])

        fig, ax = plt.subplots(1, 1, figsize=(10, 8), dpi=300)

        # Plot DEM
        rasterio.plot.show(dem_data, ax=ax, transform=dem_rio.transform,
                          cmap='Greys', alpha=0.7, zorder=-10)

        # Plot pathlines
        if time_col:
            shp_pathlines.plot(ax=ax, column=time_col, cmap='jet', lw=1, norm=norm, zorder=1)
            shp_endpoints.plot(ax=ax, column=time_col, cmap='jet', lw=0.5, markersize=20,
                              legend=False, norm=norm, zorder=2, edgecolor='k')
        else:
            shp_pathlines.plot(ax=ax, color='green', lw=1, alpha=0.7, zorder=1)
            shp_endpoints.plot(ax=ax, color='red', markersize=20, zorder=2, edgecolor='k')

        # Plot watershed boundary
        line.plot(ax=ax, facecolor='None', edgecolor='k', lw=2, zorder=-1)

        if time_col:
            ax.set_title('Residence times - backward from seepage [years]', fontsize=12)
            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="5%", pad=0.1)
            cbar = fig.colorbar(im, cax=cax, orientation='vertical', label='[years]')
        else:
            ax.set_title('Pathlines - backward from seepage', fontsize=12)

        fig.tight_layout()

        # Save figure
        figures_dir = os.path.join(calibration_folder, '_figures')
        toolbox.create_folder(figures_dir)
        fig.savefig(os.path.join(figures_dir, f'pathlines_{model_name}.png'), dpi=300, bbox_inches='tight')

        if CONFIG.get('display_figures', True):
            plt.show()
        plt.close(fig)

        print("      ✓ Pathlines plots created")
        return results

    except Exception as e:
        print(f"      ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return results


def ex09_plot_concentration(results):
    """EXEMPLE 09 - PLOT CONCENTRATION: Animated concentration maps with boxplot+recharge+GIF"""
    print("\n  • Create concentration animation...")

    if not results:
        return results

    try:
        BV = results.get('BV')
        model_modflow = results.get('model_modflow')
        model_mt3dms = results.get('model_mt3dms')
        model_name = results.get('model_name')
        calibration_folder = results.get('calibration_folder')
        stable_folder = results.get('stable_folder')
        R_mm_day_filt = results.get('R_mm_day_filt')
        vers = results.get('vers', 'TRANS1')  # Get version for filename

        if model_mt3dms is None:
            print("      ⚠ MT3DMS results not available")
            return results

        print("      • Reading concentration data...")
        ucnfile = os.path.join(model_modflow.full_path, f'{model_mt3dms.model_name_mt}.UCN')
        if not os.path.exists(ucnfile):
            print(f"      ⚠ UCN file not found: {ucnfile}")
            return results

        ucnobj = bf.UcnFile(ucnfile)
        concobj_1c = ucnobj.get_alldata(mflay=None)
        concobj_1c_fil = concobj_1c.copy() * 1000
        concobj_1c_fil[concobj_1c_fil >= 1e30] = np.nan

        figures_dir = os.path.join(calibration_folder, '_figures')
        toolbox.create_folder(figures_dir)

        print("      • Creating frames...")
        wbt.hillshade(os.path.join(stable_folder, 'geographic/watershed_dem.tif'),
                     os.path.join(stable_folder, 'geographic/watershed_hill.tif'))

        dem = rasterio.open(os.path.join(stable_folder, 'geographic/watershed_dem.tif'))
        hill = rasterio.open(os.path.join(stable_folder, 'geographic/watershed_hill.tif'))

        # Process concentration data for statistics
        concobj_1c_fil_surf = {}
        the_mins = []
        the_maxs = []
        all_box_stats = []
        mean_vals = []
        mean_times = []

        for i in range(min(10, model_mt3dms.model_modflow.nper)):
            seep = imageio.imread(os.path.join(model_modflow.full_path, f'_postprocess/_rasters/outflow_drain_t({int(i)}).tif'))
            concobj_1c_fil_surf[i] = concobj_1c_fil[i + 1][0]
            concobj_1c_fil_surf[i] = np.ma.masked_where(seep <= 0, concobj_1c_fil_surf[i])

            the_mins.append(np.nanmin(concobj_1c_fil_surf[i]))
            the_maxs.append(np.nanmax(concobj_1c_fil_surf[i]))

            # Calculate boxplot statistics
            xi = concobj_1c_fil_surf[i].flatten()
            xi = xi[~np.isnan(xi)]

            if xi.size > 0:
                xpos = mdates.date2num(R_mm_day_filt.index[i])
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
                all_box_stats.append((xpos, box_stats))

        the_min = np.nanmin(the_mins) if the_mins else 30
        the_max = np.nanmax(the_maxs) if the_maxs else 100

        # Create figures with both boxplot and concentration map
        for i in range(len(concobj_1c_fil_surf)):
            conc_plt = concobj_1c_fil_surf[i]

            fig, ax = plt.subplots(2, 1, figsize=(10, 12), dpi=300, gridspec_kw={'height_ratios': [1, 3]})

            # --- SUBPLOT 1: Boxplot with recharge ---
            axb = ax[0].twinx()
            ax[0].zorder = 1
            axb.zorder = 0
            ax[0].patch.set_visible(False)

            # Draw boxplots
            for xpos, box_stat in all_box_stats:
                ax[0].bxp(box_stat, positions=[xpos], widths=5, showfliers=False,
                        showmeans=True, meanline=False,
                        boxprops=dict(color='forestgreen', alpha=1, linewidth=1),
                        medianprops=dict(color='forestgreen', linewidth=1),
                        meanprops=dict(marker='o', markerfacecolor='k', markeredgecolor='k', markersize=5),
                        whiskerprops=dict(linestyle='-', linewidth=0),
                        capprops=dict(linewidth=0),
                        zorder=1)

            if all_box_stats:
                xpos = all_box_stats[-1][0]
                ax[0].axvline(x=xpos, color='black', linestyle='--', lw=0.5, zorder=-1)

            ax[0].set_ylabel('[NO3] mg/L', color='forestgreen')
            ax[0].set_title(f'Concentration dynamics - {model_name}', fontsize=10)
            ax[0].xaxis.set_major_locator(mdates.MonthLocator(bymonthday=1))
            ax[0].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            ax[0].tick_params(axis='x', labelrotation=90, labelsize=8)
            ax[0].set_ylim(the_min - 10, the_max + 10)

            if mean_vals and mean_times:
                ax[0].plot(mean_times, mean_vals, color='black', lw=2, linestyle='-', zorder=2)

            if R_mm_day_filt is not None:
                axb.step(R_mm_day_filt.index, R_mm_day_filt * 30, lw=2, color='dodgerblue', zorder=0)
                axb.set_ylabel('Recharge [mm/month]', color='dodgerblue')
                ax[0].set_xlim(R_mm_day_filt.index[0], R_mm_day_filt.index[-1])

            # --- SUBPLOT 2: Concentration map ---
            norm = mcolors.LogNorm(vmin=max(30, the_min), vmax=min(100, the_max))
            sm = cm.ScalarMappable(cmap='turbo', norm=norm)
            sm.set_array([])

            rasterio.plot.show(np.ma.masked_where(hill.read(1) < 0, hill.read(1)),
                             ax=ax[1], transform=hill.transform, cmap='Greys_r', alpha=0.75, zorder=-10)
            rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, conc_plt),
                             ax=ax[1], transform=dem.transform, cmap='turbo', alpha=1, zorder=1, norm=norm)

            shp_bv = gpd.read_file(BV.geographic.watershed_shp)
            shp_hydro = gpd.read_file(BV.hydrography.streams)
            shp_bv.plot(ax=ax[1], facecolor='None', lw=3, zorder=2)
            shp_hydro.plot(ax=ax[1], color='navy', lw=1, zorder=0)

            divider = make_axes_locatable(ax[1])
            cax = divider.new_vertical(size='5%', pad=0.6, pack_start=True)
            fig.add_axes(cax)
            cbar = fig.colorbar(sm, cax=cax, orientation='horizontal', label='[NO3] mg/L')
            fig.tight_layout()

            fig.savefig(os.path.join(figures_dir, f'{vers}_{i}_{model_name}.png'), dpi=300, bbox_inches='tight')

            # Show first frame only to avoid too many pop-ups
            if i == 0 and CONFIG.get('display_figures', True):
                plt.show()
            plt.close(fig)

        print("      • Creating GIF...")
        filenames = sorted(glob.glob(os.path.join(figures_dir, f'{vers}*.png')))
        if len(filenames) > 1:
            images = [Image.open(img) for img in filenames]
            images[0].save(os.path.join(figures_dir, f'concentration_{model_name}.gif'),
                          save_all=True, append_images=images[1:], optimize=True, duration=200, loop=0)
            print("      ✓ Concentration animation created")
        elif len(filenames) == 1:
            print(f"      ⚠ Only 1 frame found, skipping GIF creation")
        else:
            print(f"      ⚠ No concentration frames found")

        return results

    except Exception as e:
        print(f"      ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return results


def ex09_plot_animation_interactive(results):
    """EXEMPLE 09 - PLOT ANIMATION INTERACTIVE: Web animation with Plotly"""
    print("\n  • Create interactive web animation (Plotly)...")

    if not results:
        return results

    try:
        model_name = results.get('model_name')
        calibration_folder = results.get('calibration_folder')
        vers = results.get('vers', 'TRANS1')  # Get version for filename pattern

        if model_name is None:
            print("      ⚠ model_name not found")
            return results

        # Collect PNG files from figures directory
        figures_dir = os.path.join(calibration_folder, '_figures')
        # Search for concentration animation PNG files using pattern: TRANS1*.png
        begin_by = os.path.join(figures_dir, vers)
        filenames = sorted(glob.glob(begin_by + '*.png'), key=os.path.getmtime)

        if not filenames:
            print(f"      ⚠ No PNG files found matching {begin_by}*.png")
            return results

        print(f"      • Found {len(filenames)} frames...")

        # Convert images to base64
        def image_to_base64(path):
            with Image.open(path) as img:
                with BytesIO() as stream:
                    img.save(stream, format="png")
                    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("utf-8")

        image_sources = [image_to_base64(p) for p in filenames]

        if not image_sources:
            print("      ⚠ No images could be converted to base64")
            return results

        print(f"      • Building animation with {len(image_sources)} frames...")

        # Create frames for animation with proper transitions
        frames = []
        for i, src in enumerate(image_sources):
            frame_data = go.Frame(
                data=[],
                name=str(i),
                layout=go.Layout(
                    title_text=f"{model_name} - Frame {i+1}/{len(image_sources)}",
                    images=[dict(
                        source=src,
                        xref="paper",
                        yref="paper",
                        x=0.5, y=0.5,
                        sizex=1, sizey=1,
                        xanchor="center",
                        yanchor="middle",
                        sizing="contain"
                    )]
                )
            )
            frames.append(frame_data)

        # Create initial figure with first image
        initial_image = dict(
            source=image_sources[0],
            xref="paper",
            yref="paper",
            x=0.5, y=0.5,
            sizex=1, sizey=1,
            xanchor="center",
            yanchor="middle",
            sizing="contain"
        )

        # Create figure with controls
        fig = go.Figure(
            data=[],
            layout=go.Layout(
                title={
                    'text': f"Concentration Dynamics - {model_name}<br><sub>Click PLAY to animate through time</sub>",
                    'x': 0.5,
                    'xanchor': 'center'
                },
                images=[initial_image],
                updatemenus=[{
                    'type': 'buttons',
                    'showactive': True,
                    'buttons': [
                        {
                            'label': '▶ PLAY',
                            'method': 'animate',
                            'args': [None, {
                                'frame': {'duration': 600, 'redraw': True},
                                'fromcurrent': True,
                                'transition': {'duration': 100, 'easing': 'quadratic-in-out'}
                            }]
                        },
                        {
                            'label': '⏸ PAUSE',
                            'method': 'animate',
                            'args': [[None], {
                                'frame': {'duration': 0, 'redraw': False},
                                'mode': 'immediate',
                                'transition': {'duration': 0}
                            }]
                        }
                    ],
                    'x': 0.05,
                    'y': 0.05,
                    'xanchor': 'left',
                    'yanchor': 'bottom'
                }],
                sliders=[{
                    'active': 0,
                    'steps': [{
                        'args': [[str(i)], {
                            'frame': {'duration': 0, 'redraw': True},
                            'mode': 'immediate',
                            'transition': {'duration': 100}
                        }],
                        'method': 'animate',
                        'label': f'{i+1}/{len(image_sources)}'
                    } for i in range(len(image_sources))],
                    'x': 0.1,
                    'y': 0,
                    'currentvalue': {
                        'prefix': 'Timeframe: ',
                        'visible': True,
                        'xanchor': 'center',
                        'font': {'size': 12}
                    },
                    'transition': {'duration': 100},
                    'len': 0.8
                }],
                width=1000,
                height=700,
                margin=dict(t=100, b=100, l=50, r=50),
                xaxis={'visible': False},
                yaxis={'visible': False}
            ),
            frames=frames
        )

        # Save to HTML and show in browser
        output_file = os.path.join(figures_dir, f'animation_{model_name}.html')
        fig.write_html(output_file)
        print(f"      ✓ Animation saved to: {output_file}")

        # Open in browser
        fig.show("browser")

        return results

    except Exception as e:
        print(f"      ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return results


def ex09_recharge_plot(results):
    """EXEMPLE 09 - RECHARGE avec plot spécifique + synthetic recharge"""

    if not results:
        return None

    try:
        print("  • Create plots (specific to Ex09)...")
        BV = results['BV']

        R_mm_day = BV.climatic.recharge
        r_mm_day = BV.climatic.runoff

        fig, axs = plt.subplots(2, 1, figsize=(8, 5), sharex=True)
        axs = axs.ravel()

        ax = axs[0]
        ax.plot(7 * R_mm_day, label='Recharge', c='navy', lw=1)
        ax.fill_between(R_mm_day.index, 7 * R_mm_day, (7 * R_mm_day) + (7 * r_mm_day),
                        label='Recharge + Runoff', color='dodgerblue', lw=0.5, alpha=1)
        ax.set_ylabel('[mm/week]')
        ax.legend(loc='upper right')
        ax.set_title('No log', fontsize=8)

        ax = axs[1]
        ax.plot(7 * R_mm_day, label='Recharge', c='navy', lw=1)
        ax.fill_between(R_mm_day.index, 7 * R_mm_day, (7 * R_mm_day) + (7 * r_mm_day),
                        label='Recharge + Runoff', color='dodgerblue', lw=0.5, alpha=1)
        ax.set_yscale('log')
        ax.set_xlabel('Date')
        ax.set_title('Log', fontsize=8)
        fig.tight_layout()

        # Synthetic recharge filtering
        print("  • Create synthetic recharge...")
        R_mm_day_filt = select_period(R_mm_day, 2003, 2003) * 0
        R_mm_day_filt[R_mm_day_filt.index.month.isin([3, 4, 5, 6, 7, 8, 9, 10])] = 0
        R_mm_day_filt[R_mm_day_filt.index.month.isin([1, 2, 11, 12])] = 2

        fig, ax = plt.subplots(1, 1, figsize=(8, 3), sharex=True)
        ax.plot(7 * R_mm_day_filt, label='Recharge', c='dodgerblue', lw=2)
        ax.set_title('Synthetic recharge [mm/week]')
        fig.tight_layout()

        results['R_mm_day'] = R_mm_day
        results['R_mm_day_filt'] = R_mm_day_filt

        print("✓ Recharge calculated\n")
        return results
    except Exception as e:
        print(f"✗ Error: {e}\n")
        return results


def ex09_modeling(results):
    """EXEMPLE 09 - MODELING: MODFLOW + MODPATH + MT3DMS"""
    print("\n" + "="*70)
    print("EXEMPLE 09 - MODELING".center(70))
    print("="*70)

    if not results:
        return None

    try:
        p = PARAMS["ex09"]
        BV = results['BV']
        config = MODELING_CONFIG.get('ex09', {})

        vers = p["vers"]
        model_name = (
            f"{vers}_K{p['the_K0'] / 24 / 3600:.1e}_"
            f"a{p['alpha']:.1f}_Sy{p['the_sy0'] * 100:.1f}"
        )
        print(f"Model: {model_name}")

        # Use generic modflow function from modeling_workflow
        print("   Create and run MODFLOW model...")
        modflow_result = modflow(BV, model_name, p['the_K0'], config)

        # Use generic modpath function from modeling_workflow
        print("   Create and run MODPATH model...")
        modflow_result['BV'] = BV
        modpath_result = modpath(BV, modflow_result, for_calib=True)

        # Update results with modeling results
        results['BV'] = modpath_result['BV']
        results['model_name'] = model_name
        results['vers'] = vers
        results['model_modflow'] = modflow_result['model_modflow']
        results['success_modflow'] = modflow_result['success']
        results['model_modpath'] = modpath_result['model_modpath']
        results['success_modpath'] = modpath_result['success']

        print("✓ Modeling completed\n")
        return results

    except Exception as e:
        print(f"✗ Error: {e}\n")
        import traceback
        traceback.print_exc()
        return results


def ex09_plot(results):
    """EXEMPLE 09 - PLOT (COMPLETE): All visualizations"""
    print("\n" + "="*70)
    print("EXEMPLE 09 - PLOT (COMPLETE)".center(70))
    print("="*70)

    if not results:
        return None

    try:
        # Call all plot functions in sequence
        print("\n[PLOT 1] Streamflow and matching streams...")
        results = ex09_plot_streamflow(results)

        print("\n[PLOT 2] Piezometry...")
        results = ex09_plot_piezometry(results)

        print("\n[PLOT 3] Pathlines and residence times...")
        results = ex09_plot_pathlines(results)

        print("\n[PLOT 4] Concentration animation...")
        results = ex09_plot_concentration(results)

        print("\n[PLOT 5] Interactive web animation...")
        results = ex09_plot_animation_interactive(results)

        print("\n✓ All plots completed\n")
        return results
    except Exception as e:
        print(f"✗ Error: {e}\n")
        import traceback
        traceback.print_exc()
        return results


# ============================================================================
# WORKFLOW VALIDATION & DOCUMENTATION
# ============================================================================

# Define the correct workflow order and dependencies for each example
WORKFLOW_DEFINITION = {
    "ex03": [
        {
            "step": 1,
            "section": "watershed",
            "function": "watershed()",
            "requires": [],
            "provides": ["BV", "stable_folder", "simulations_folder", "data_path"]
        },
        {
            "step": 2,
            "section": "data",
            "function": "data()",
            "requires": ["BV"],
            "provides": ["geology", "hydrography", "hydrometry"]
        },
        {
            "step": 3,
            "section": "recharge",
            "function": "recharge() + ex03_recharge_plot()",
            "requires": ["BV", "data_path"],
            "provides": ["climatic", "recharge_data", "runoff_data"]
        },
        {
            "step": 4,
            "section": "parametrization",
            "function": "parametrization()",
            "requires": ["BV", "climatic"],
            "provides": ["settings", "hydraulic_params"]
        },
        {
            "step": 5,
            "section": "modeling",
            "function": "modeling()",
            "requires": ["BV", "settings", "hydraulic_params"],
            "provides": ["list_model_name", "list_success_modflow", "list_model_modflow"]
        },
        {
            "step": 6,
            "section": "plot",
            "function": "ex03_plot()",
            "requires": ["list_model_name", "list_model_modflow"],
            "provides": ["visualizations"]
        }
    ],
     "ex09": [
        {
            "step": 1,
            "section": "watershed",
            "function": "watershed()",
            "requires": [],
            "provides": ["BV", "stable_folder", "calibration_folder", "data_path"]
        },
        {
            "step": 2,
            "section": "data",
            "function": "data()",
            "requires": ["BV"],
            "provides": ["hydrography", "subbasins"]
        },
        {
            "step": 3,
            "section": "recharge",
            "function": "recharge() + ex09_recharge_plot()",
            "requires": ["BV", "data_path"],
            "provides": ["R_mm_day", "R_mm_day_filt"]
        },
        {
            "step": 4,
            "section": "parametrization",
            "function": "parametrization()",
            "requires": ["BV", "R_mm_day"],
            "provides": [
                "settings",
                "hydraulic_params",
                "climatic_params",
                "recharge",
                "runoff"
            ]
        },
        {
            "step": 5,
            "section": "modeling",
            "function": "modeling()",
            "requires": ["BV", "settings", "hydraulic_params", "climatic_params"],
            "provides": ["model_modflow", "model_name", "success_modflow"]
        },
        {
            "step": 6,
            "section": "matching_streams",
            "function": "ex09_matching_streams()",
            "requires": ["BV", "model_name", "model_modflow"],
            "provides": ["matching_streams"]
        },
        {
            "step": 7,
            "section": "modpath",
            "function": "ex09_modpath()",
            "requires": ["BV", "model_modflow", "success_modflow"],
            "provides": ["model_modpath", "success_modpath"]
        },
        {
            "step": 8,
            "section": "mt3dms",
            "function": "ex09_mt3dms()",
            "requires": ["BV", "model_modflow", "success_modflow"],
            "provides": ["model_mt3dms", "success_mt3dms"]
        },
        {
            "step": 9,
            "section": "plot_streamflow",
            "function": "ex09_plot_streamflow()",
            "requires": ["BV", "model_modflow", "success_modflow", "data_path"],
            "provides": ["streamflow_visualization"]
        },
        {
            "step": 10,
            "section": "plot_piezometry",
            "function": "ex09_plot_piezometry()",
            "requires": ["BV", "model_modflow", "success_modflow"],
            "provides": ["piezometry_visualization"]
        },
        {
            "step": 11,
            "section": "plot_pathlines",
            "function": "ex09_plot_pathlines()",
            "requires": ["BV", "model_modpath", "success_modpath"],
            "provides": ["pathlines_visualization"]
        },
        {
            "step": 12,
            "section": "plot_concentration",
            "function": "ex09_plot_concentration()",
            "requires": ["BV", "model_mt3dms", "success_mt3dms"],
            "provides": ["concentration_visualization"]
        },
        {
            "step": 13,
            "section": "plot_animation_interactive",
            "function": "ex09_plot_animation_interactive()",
            "requires": ["model_name", "calibration_folder", "model_modflow"],
            "provides": ["interactive_web_animation"]
        }
    ]
}


def print_workflow_definition(example_key):
    """Print the correct workflow order and dependencies"""
    print("\n" + "="*70)
    print(f"WORKFLOW DEFINITION - {example_key.upper()}".center(70))
    print("="*70)

    workflow = WORKFLOW_DEFINITION.get(example_key, [])

    for step in workflow:
        print(f"\n  Step {step['step']}: {step['section'].upper()}")
        print(f"  └─ Function: {step['function']}")
        print(f"  └─ Requires: {', '.join(step['requires']) if step['requires'] else 'Nothing'}")
        print(f"  └─ Provides: {', '.join(step['provides'])}")


def validate_results_state(results, expected_keys, step_name=""):
    """Validate that results dict contains expected keys"""
    if results is None:
        print(f"\n✗ VALIDATION ERROR at {step_name}: results dict is None!")
        return False

    missing = [key for key in expected_keys if key not in results]

    if missing:
        print(f"\n✗ VALIDATION ERROR at {step_name}:")
        print(f"   Missing keys: {missing}")
        print(f"   Available keys: {list(results.keys())}")
        return False

    return True


def trace_workflow_execution(example_key, sections):
    """Trace and validate the workflow order before execution"""
    print("\n" + "="*70)
    print("WORKFLOW EXECUTION PLAN".center(70))
    print("="*70)

    workflow = WORKFLOW_DEFINITION.get(example_key, [])

    print(f"\n  Example: {example_key.upper()}")
    print(f"  Enabled sections: {[k for k, v in sections.items() if v]}\n")

    enabled_steps = []
    for step in workflow:
        is_enabled = sections.get(step['section'], False)
        status = "ENABLED" if is_enabled else "DISABLED"
        print(f"  [{step['step']}] {step['section']:20s} {status}")

        if is_enabled:
            enabled_steps.append(step)

    print("\n  Execution order:")
    for i, step in enumerate(enabled_steps, 1):
        print(f"    {i}. {step['function']}")

    # Validate dependencies
    print("\n  Dependency validation:")
    accumulated_keys = []
    valid = True

    for step in enabled_steps:
        missing = [k for k in step['requires'] if k not in accumulated_keys]

        if missing:
            print(f"     {step['section']}: Missing {missing}")
            valid = False
        else:
            print(f"    {step['section']}: All dependencies satisfied")

        for key in step['provides']:
            if key not in accumulated_keys:
                accumulated_keys.append(key)

    if valid:
        print("\n   All dependencies satisfied - workflow is VALID")
    else:
        print("\n   Some dependencies missing - check CONFIG sections")

    return valid, enabled_steps


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Execute according to CONFIG"""

    example_key = CONFIG["example"]
    sections = CONFIG["sections"]
    example_names = {"ex03": "EXEMPLE 03", "ex09": "EXEMPLE 09"}

    print("\n" + "="*70)
    print("HYDROMODPY LAUNCHER - Single Example Mode".center(70))
    print("="*70)

    # 1. Afficher la définition du workflow
    print_workflow_definition(example_key)

    # 2. Tracer et valider l'ordre d'exécution
    workflow_valid, enabled_steps = trace_workflow_execution(example_key, sections)

    if not workflow_valid:
        print("\n⚠ WARNING: Workflow dependencies are not satisfied!")
        response = input("Continue anyway? (y/n): ")
        if response.lower() != 'y':
            print("✗ Execution cancelled")
            return

    print(f"\n✓ Running: {example_names.get(example_key, example_key)}\n")

    # 3. Exécution avec validation
    results = None
    step_counter = 1

    # STEP 1: Watershed
    if sections.get("watershed"):
        print(f"\n[STEP {step_counter}] Executing: watershed('{example_key}')")
        results = watershed(example_key)
        if results:
            validate_results_state(results, ["BV", "data_path"], "watershed")
            print(f"     ✓ Results keys: {list(results.keys())}")
        step_counter += 1

    # STEP 2: Data
    if results and sections.get("data"):
        current_example = results.get('example_key', CONFIG["example"])
        print(f"\n[STEP {step_counter}] Executing: data() for {current_example}")
        results = data(results)
        if results:
            validate_results_state(results, ["BV"], "data")
        step_counter += 1

    # STEP 3: Recharge
    if results and sections.get("recharge"):
        print(f"\n[STEP {step_counter}] Executing: recharge() + {example_key}_recharge_plot()")
        results = recharge(results, example_key)
        if example_key == "ex03":
            results = ex03_recharge_plot(results)
            # ex03 uses recharge_from_params - no need for R_mm_day validation
            if results:
                validate_results_state(results, ["BV"], "recharge")
        elif example_key == "ex09":
            results = ex09_recharge_plot(results)
            # ex09 uses recharge_from_results - needs R_mm_day
            if results:
                validate_results_state(results, ["BV", "R_mm_day"], "recharge")
        step_counter += 1

    # STEP 4: Parametrization s
    if results and sections.get("parametrization"):
        current_example = results.get('example_key', CONFIG["example"])
        print(f"\n[STEP {step_counter}] Executing: parametrization() for {current_example}")
        results = parametrization(results)
        if results:
            validate_results_state(results, ["BV"], "parametrization")
            print("   Hydraulic parameters configured")
        step_counter += 1

    # STEP 5: Modeling
    if results and sections.get("modeling"):
        current_example = results.get('example_key', CONFIG["example"])
        print(f"\n[STEP {step_counter}] Executing: modeling() for {current_example}")

        if current_example == "ex03":
            results = modflow_ex03(results['BV'], results, MODELING_CONFIG["ex03"])
        elif current_example == "ex09":
            results = modflow_ex09(results['BV'], results, MODELING_CONFIG["ex09"])

        if results:
            validate_results_state(results, ["BV", "model_name", "success_modflow"], "modeling")
            if results.get('success_modflow'):
                print(f"     MODFLOW successful: {results['model_name']}")
            else:
                print(f"     MODFLOW failed: {results['model_name']}")
        step_counter += 1

        # STEP 6: Matching streams
        if sections.get("matching_streams") and results.get('success_modflow'):
            print(f"\n[STEP {step_counter}] Executing: ex09_matching_streams()")
            results = ex09_matching_streams(results)
            if results:
                validate_results_state(results, ["matching_streams"], "matching_streams")
            step_counter += 1
        elif sections.get("matching_streams") and not results.get('success_modflow'):
            print(f"\n[STEP {step_counter}] ⚠ Skipping matching_streams (MODFLOW failed)")
            step_counter += 1

        # STEP 7: MODPATH
        if sections.get("modpath") and results.get('success_modflow'):
            print(f"\n[STEP {step_counter}] Executing: modpath()")
            results = modpath_ex09(results)

            if results:
                validate_results_state(results, ["model_modpath", "success_modpath"], "modpath")
            step_counter += 1
        elif sections.get("modpath") and not results.get('success_modflow'):
            print(f"\n[STEP {step_counter}] ⚠ Skipping modpath (MODFLOW failed)")
            step_counter += 1

        # STEP 8: MT3DMS
        if sections.get("mt3dms") and results.get('success_modflow'):
            print(f"\n[STEP {step_counter}] Executing: mt3dms()")
            results = mt3dms_ex09(results)
            if results:
                validate_results_state(results, ["model_mt3dms", "success_mt3dms"], "mt3dms")
            step_counter += 1
        elif sections.get("mt3dms") and not results.get('success_modflow'):
            print(f"\n[STEP {step_counter}] ⚠ Skipping mt3dms (MODFLOW failed)")
            step_counter += 1

    # STEP 9/6: Plot (generic for ex03, advanced for ex09)
    if results and sections.get("plot"):
        print(f"\n[STEP {step_counter}] Executing: {example_key}_plot()")

        if example_key == "ex03":
            results = ex03_plot(results)

        elif example_key == "ex09":
            print("\n" + "="*70)
            print("EXEMPLE 09 - PLOT (ADVANCED)".center(70))
            print("="*70)

            # Streamflow plot (always available)
            if results.get('success_modflow'):
                print("\n  • Streamflow visualization...")
                results = ex09_plot_streamflow(results)

                print("\n  • Piezometry visualization...")
                results = ex09_plot_piezometry(results)

                # Pathlines (if MODPATH successful)
                if results.get('success_modpath'):
                    print("\n  • Pathlines visualization...")
                    results = ex09_plot_pathlines(results)
                else:
                    print("\n  • ⚠ Skipping pathlines (MODPATH not available)")

                # Concentration (if MT3DMS successful)
                if results.get('success_mt3dms'):
                    print("\n  • Concentration visualization...")
                    results = ex09_plot_concentration(results)
                else:
                    print("\n  • ⚠ Skipping concentration (MT3DMS not available)")
            else:
                print("\n  • ⚠ Skipping plots (MODFLOW failed)")

        step_counter += 1

    # Ex09 only: Interactive Plotly animation (depends on successful MODFLOW)
    if example_key == "ex09" and results:
        if sections.get("plot_animation_interactive") and results.get('success_modflow'):
            print(f"\n[STEP {step_counter}] Executing: ex09_plot_animation_interactive()")
            results = ex09_plot_animation_interactive(results)
            step_counter += 1
        elif sections.get("plot_animation_interactive") and not results.get('success_modflow'):
            print(f"\n[STEP {step_counter}] ⚠ Skipping animation (MODFLOW failed)")
            step_counter += 1

    print("\n" + "="*70)
    print("✓ EXECUTION COMPLETED".center(70))
    print("="*70)

    # 4. Afficher le résumé final
    if results:
        print(f"\n  Final results keys: {sorted(results.keys())}\n")

        # Show success summary
        print("  Execution summary:")
        if results.get('success_modflow'):
            print(f"    • MODFLOW:  {results['model_name']}")
        else:
            print("    • MODFLOW:  Failed")

        if results.get('success_modpath'):
            print(f"    • MODPATH:  {results.get('model_name', 'Success')}")
        else:
            print("    • MODPATH:  Failed")

        if results.get('success_mt3dms'):
            print(f"    • MT3DMS:  {results.get('scenario', 'Success')}")
        else:
            print("    • MT3DMS:  Failed")
        print()

    return results


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
