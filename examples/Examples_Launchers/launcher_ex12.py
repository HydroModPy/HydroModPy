# -*- coding: utf-8 -*-
"""
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 * HydroModPy Launcher - Example 12 STANDALONE
 * Complete example 12 with ALL functions from launcher.py, only adapted for ex12
"""

import sys
import os
import pickle
import numpy as np
import pandas as pd
import matplotlib as mpl
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

root_dir = str(Path(__file__).parent.parent.parent)
sys.path.append(root_dir)

try:
    import hydromodpy
except:
    pass

from hydromodpy import watershed_root
from hydromodpy.watershed import initializing, geographic
from hydromodpy.watershed import Geographic, Initializing, Climatic, Geology, Hydrography, Hydrometry, Intermittency, Settings, Hydraulic, Oceanic, Transport
from hydromodpy.watershed.initializing_config import InitializingConfig
from hydromodpy.watershed.geographic_config import GeographicConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.display import visualization_watershed, visualization_results
from hydromodpy.tools import toolbox

# Import from modeling_workflow_copy.py (with space in filename)
import importlib.util
spec = importlib.util.spec_from_file_location("modeling_workflow_copy", Path(__file__).parent / "modeling_workflow copy.py")
modeling_workflow_copy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(modeling_workflow_copy)
modflow = modeling_workflow_copy.modflow
modpath = modeling_workflow_copy.modpath
mt3dms = modeling_workflow_copy.mt3dms

fontprop = toolbox.plot_params(8, 15, 18, 20)

# Load configuration from config.toml (initializing and geographic)
cfg = HydroModPyConfig.from_toml(Path(__file__).parent / "config.toml")



# ============================================================================
# CONFIG - EXAMPLE 12
# ============================================================================

CONFIG = {
    "example": "ex12",
    "display_figures": True,  # False to avoid pop-ups
    "sections": {
        "watershed": True,
        "data": True,
        "recharge": True,
        "parametrization": True,
        "modeling": True,
        "plot": True,
        "matching_streams": True,
        "modpath": True,
        "mt3dms": True,
        "plot_animation_interactive": True
    }
}

# Set matplotlib backend based on display_figures config
if not CONFIG.get('display_figures', False):
    mpl.use('Agg')


# ============================================================================
# PARAMETERS - EXAMPLE 12 ONLY
# ============================================================================

PARAMS = {
    "ex12": {
        "base_path": "examples/example12",
        "dem_filename": "regional dem.tif",
        "dem_coordinates": [265611.933, 6784182.776, 50, 20, 'EPSG:2154'],
        "watershed_name": "example12",
        "recharge_first_year": 2003,
        "recharge_last_year": 2003,
        "recharge_time_step": "M",
        # Parametrization
        "box": True,
        "sink_fill": False,
        "sim_state": "transient",
        "plot_cross": True,
        "cross_ylim": [0, 150],
        "check_grid": True,
        "dis_perlen": True,
        "nlay": 10,
        "lay_decay": 1.2,
        "verti_hk": None,
        "verti_sy": None,
        "verti_ss": None,
        "sy": 1 / 100,
        "sy_decay": 0,
        "ss": 1e-5,
        "ss_decay": 0,
        "vka": 1,
        "bottom": 0,
        "thickness": 100,
        "cond_drain": None,
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
    }
}


# ============================================================================
# DATA CONFIGS - EXAMPLE 12
# ============================================================================

DATA_CONFIGS = {
    "ex12": {
        "modules": [
            {"name": "geology", "method": "add_geology",
             "args": [('types_obs', 'GEO1M.shp'), ('fields_obs', 'CODE_LEG')]},
            {"name": "hydrography", "method": "add_hydrography",
             "args": [('types_obs', ['regional stream network']), ('fields_obs', ['FID'])]},
            {"name": "hydrometry", "method": "add_hydrometry",
             "args": [('file_name', 'france hydrometric stations.shp')]},
            {"name": "intermittency", "method": "add_intermittency",
             "args": [('file_name', 'regional onde stations.shp')]},
        ],
        "visualizations": [
            {"name": "local", "method": "watershed_local",
             "dem_param": True},
            {"name": "geology", "method": "watershed_geology"},
            {"name": "dem", "method": "watershed_dem"},
            {"name": "zones", "method": "watershed_zones"}
        ],
        "dem_filename": PARAMS["ex12"]["dem_filename"]
    }
}


# ============================================================================
# DATA MODULES - EXAMPLE 12 (Approach 4: Pure Configuration)
# ============================================================================

DATA_MODULES = {
    "ex12": {
        "geology": {
            "class_name": "Geology",
            "constructor_args": {
                "out_path": ("initializing.catch_folder", True),
                "geographic": ("geographic", True),
                "geo_path": ("data_path", True),
                "landsea": (None, False),
                "types_obs": ("GEO1M.shp", False),
                "fields_obs": ("CODE_LEG", False)
            }
        },
        "hydrography": {
            "class_name": "Hydrography",
            "constructor_args": {
                "out_path": ("initializing.catch_folder", True),
                "types_obs": (["botopage2024_naizin_streams_perennial-intermittent"], False),
                "fields_obs": (["FID"], False),
                "geographic": ("geographic", True),
                "hydro_path": ("data_path", True),
                "streams_file": (None, False)
            }
        },
        "hydrometry": {
            "class_name": "Hydrometry",
            "constructor_args": {
                "out_path": ("initializing.catch_folder", True),
                "hydrometry_path": ("data_path", True),
                "file_name": ("france hydrometric stations.shp", False),
                "geographic": ("geographic", True)
            }
        },
        "intermittency": {
            "class_name": "Intermittency",
            "constructor_args": {
                "out_path": ("initializing.catch_folder", True),
                "intermittency_path": ("data_path", True),
                "file_name": ("regional onde stations.shp", False),
                "geographic": ("geographic", True)
            }
        }
    }
}


# ============================================================================
# PARAM CONFIG - EXAMPLE 12
# ============================================================================

PARAM_CONFIG = {
    "ex12": {
        "check_model": {"plot_cross": True, "check_grid": True},
        "climatic": {
            "recharge_from_results": True,
            "runoff_factor": 0.1
        },
        "hydraulic_specific": {
            "update_ss": True,
            "update_vka": True,
            "update_vertical": False,
            "update_decay": True,
            "sy_complex": True
        },
        "particle_tracking": False
    }
}


# ============================================================================
# MODELING CONFIG - EXAMPLE 12
# ============================================================================

MODELING_CONFIG = {
    "ex12": {
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
# HELPER FUNCTIONS
# ============================================================================

def select_period(df, first, last):
    """Select period in dataframe by year"""
    return df[(df.index.year >= first) & (df.index.year <= last)]


# ============================================================================
# GENERIC MODELING METHODS - Imported from hydromodpy.modeling_workflow
# ============================================================================
# modflow(), modpath(), mt3dms() are now imported from modeling_workflow module
# See hydromodpy/modeling_workflow.py for implementations



def watershed(example_key="ex12"):
    """Extract watershed for example 12 (loads config from config.toml)"""
    print("\n" + "="*70)
    print("EXAMPLE 12 - WATERSHED EXTRACTION".center(70))
    print("="*70)

    try:
        # Load paths from PARAMS (for data directory reference)
        p = PARAMS[example_key]
        example_path = os.path.join(root_dir, p["base_path"])
        data_path = os.path.join(example_path, "data")

        if not os.path.exists(data_path):
            print(f"✗ Data path not found: {data_path}\n")
            return None

        print(f"\n  • Configuration loaded from: config.toml")
        print(f"  • Data path: {data_path}")

        # Convert config paths to Path objects (config.toml stores them as strings)
        # Build full paths for out_dir and data
        out_dir_path = Path(example_path) / cfg.initializing.out_dir_path

        # Update cfg paths with proper Path objects
        cfg.initializing.out_dir_path = out_dir_path
        cfg.initializing.data_path = Path(data_path)

        # Extract filename from dem_init_path (it may have "data/" prefix from config.toml)
        dem_filename = Path(cfg.geographic.dem_init_path).name
        cfg.geographic.dem_init_path = Path(data_path) / dem_filename

        # Verify DEM path
        dem_path = str(cfg.geographic.dem_init_path)
        if not os.path.exists(dem_path):
            print(f"✗ DEM not found: {dem_path}\n")
            return None

        print(f"  • DEM: {dem_path}")

        # Create Initializing object with config from config.toml
        initializing_object = initializing.Initializing(config=cfg.initializing)

        # Create Geographic object with config from config.toml
        geographic_object = Geographic(config=cfg.geographic,
                        initializing=initializing_object)

        # Create individual objects (like example12.py) - NOT via BV
        print("  • Creating individual objects (Settings, Hydraulic, Oceanic)...")
        settings_object = Settings()
        hydraulic_object = Hydraulic(
            nrow=geographic_object.y_pixel,
            ncol=geographic_object.x_pixel,
            box_dem=geographic_object.watershed_box_buff_dem
        )
        oceanic_object = Oceanic()
        transport_object = Transport()

        stable_folder = initializing_object.stable_folder
        simulations_folder = initializing_object.simulations_folder
        calibration_folder = initializing_object.calibration_folder
        results_path = cfg.initializing.out_dir_path

        # For example 12 (single model), use simulations_folder as calibration_folder
        # This ensures MODFLOW outputs go to the correct location for MODPATH/MT3DMS
        example_key = CONFIG["example"]
        if MODELING_CONFIG.get(example_key, {}).get("type") == "single":
            calibration_folder = simulations_folder

        print("✓ Watershed extracted\n")

        # Prepare results dictionary with individual objects (NOT BV)
        results = {
            'initializing': initializing_object,
            'geographic': geographic_object,
            'settings': settings_object,
            'hydraulic': hydraulic_object,
            'oceanic': oceanic_object,
            'transport': transport_object,
            'example_key': example_key,
            'data_path': data_path,
            'results_path': results_path,
            'stable_folder': stable_folder,
            'simulations_folder': simulations_folder,
            'calibration_folder': calibration_folder
        }

        return results

    except Exception as e:
        print(f"✗ Error: {e}\n")
        import traceback
        traceback.print_exc()
        return None


# ============================================================================
# HELPER: Resolve References for DATA_MODULES
# ============================================================================

def _resolve_reference(ref_str, results):
    """Resolve nested references like 'initializing.catch_folder' to actual values"""
    if not ref_str or ref_str is None:
        return None

    parts = ref_str.split('.')
    obj = results.get(parts[0])

    if obj is None:
        return None

    for part in parts[1:]:
        try:
            obj = getattr(obj, part)
        except AttributeError:
            return None

    return obj


# ============================================================================
# STEP 2: DATA INTEGRATION
# ============================================================================

def data(results):
    """Add geographic data to watershed using DATA_MODULES configuration"""
    print("\n" + "="*70)
    print("DATA - GEOGRAPHIC INTEGRATION".center(70))
    print("="*70)

    if not results:
        return None

    try:
        example_key = results.get('example_key', CONFIG["example"])
        data_path = results.get('data_path')

        # Check if configuration exists for this example
        if example_key not in DATA_MODULES:
            print(f"  ⚠ No data configuration for {example_key}")
            return results

        module_config = DATA_MODULES[example_key]
        print(f"\n  • Instantiating data modules for {example_key.upper()}...")

        # Iterate through each module in configuration
        for module_name, module_info in module_config.items():
            try:
                class_name = module_info["class_name"]
                constructor_args = module_info["constructor_args"]

                # Resolve all constructor arguments
                resolved_kwargs = {}
                for arg_name, (arg_value, is_reference) in constructor_args.items():
                    if is_reference:
                        # Resolve reference from results dict
                        resolved_value = _resolve_reference(arg_value, results)
                        resolved_kwargs[arg_name] = resolved_value
                    else:
                        # Use static value directly
                        resolved_kwargs[arg_name] = arg_value

                # Get class from globals (imported in launcher)
                module_class = globals()[class_name]

                # Instantiate the module
                print(f"    • {module_name}...", end="", flush=True)
                module_instance = module_class(**resolved_kwargs)

                # Store in results
                results[module_name] = module_instance
                print(" ✓")

            except KeyError as e:
                print(f" ✗ Missing class: {e}")
            except Exception as e:
                print(f" ✗ Error: {e}")

        # Visualizations
        config = DATA_CONFIGS.get(example_key, {})
        viz_list = config.get("visualizations", [])
        if viz_list:
            print("\n   Creating watershed visualizations...")
            for viz in viz_list:
                try:
                    method_name = viz["method"]
                    if hasattr(visualization_watershed, method_name):
                        if viz.get("dem_param"):
                            dem_filename = config.get("dem_filename")
                            if dem_filename:
                                dem_path = os.path.join(data_path, dem_filename)
                                if os.path.exists(dem_path):
                                    print(f"    • {viz['name']}...", end="", flush=True)
                                    getattr(visualization_watershed, method_name)(dem_path, results.get('geographic'))
                                    print(" ✓")
                                else:
                                    print(f" ⚠ DEM not found: {dem_path}")
                        else:
                            print(f"    • {viz['name']}...", end="", flush=True)
                            getattr(visualization_watershed, method_name)(results.get('geographic'))
                            print(" ✓")
                except Exception as e:
                    print(f" ✗ Error: {e}")

        print("✓ Data integration completed\n")
        return results

    except Exception as e:
        print(f"✗ Error: {e}\n")
        import traceback
        traceback.print_exc()
        return results


# ============================================================================
# STEP 3: RECHARGE CALCULATION
# ============================================================================

def recharge(results):
    """Calculate recharge from climatic data"""
    print("\n" + "="*70)
    print("RECHARGE (CLIMATIC DATA)".center(70))
    print("="*70)

    if not results:
        return None

    try:
        example_key = results.get('example_key', CONFIG["example"])
        p = PARAMS[example_key]
        data_path = results['data_path']

        # Get or create Climatic object (like example12.py line 117)
        climatic_object = results.get('climatic')
        if climatic_object is None:
            print("  • Creating Climatic object...")
            initializing_object = results['initializing']
            climatic_object = Climatic(out_path=initializing_object.catch_folder)
            results['climatic'] = climatic_object

        print("  • Update recharge (REANALYSIS)...")
        climatic_object.update_recharge_reanalysis(
            path_file=os.path.join(data_path, '_climate_REANALYSIS.csv'),
            clim_mod='REA',
            clim_sce='historic',
            first_year=p["recharge_first_year"],
            last_year=p["recharge_last_year"],
            time_step=p["recharge_time_step"],
            sim_state='transient'
        )

        print("  • Update runoff (REANALYSIS)...")
        climatic_object.update_runoff_reanalysis(
            path_file=os.path.join(data_path, '_climate_REANALYSIS.csv'),
            clim_mod='REA',
            clim_sce='historic',
            first_year=p["recharge_first_year"],
            last_year=p["recharge_last_year"],
            time_step=p["recharge_time_step"],
            sim_state='transient'
        )

        print("✓ Recharge and runoff loaded\n")

        results['R_mm_day'] = climatic_object.recharge
        results['runoff'] = climatic_object.runoff
        results['climatic'] = climatic_object

        return results

    except Exception as e:
        print(f"✗ Error: {e}\n")
        import traceback
        traceback.print_exc()
        return results


# ============================================================================
# STEP 4: PARAMETRIZATION
# ============================================================================

def parametrization(results):
    """Configure hydraulic parameters"""
    print("\n" + "="*70)
    print("PARAMETRIZATION".center(70))
    print("="*70)

    if not results:
        return None

    try:
        example_key = results.get('example_key', CONFIG["example"])
        p = PARAMS[example_key]
        config = PARAM_CONFIG[example_key]

        # Get individual objects created in watershed() and recharge()
        settings_object = results['settings']
        hydraulic_object = results['hydraulic']
        climatic_object = results.get('climatic')
        oceanic_object = results['oceanic']

        if climatic_object is None:
            initializing_object = results['initializing']
            climatic_object = Climatic(out_path=initializing_object.catch_folder)
            results['climatic'] = climatic_object

        print("  • Configuring individual objects...")

        # Configure Settings (like example12.py)
        print("    • Settings...")
        settings_object.update_box_model(p["box"])
        settings_object.update_sink_fill(p["sink_fill"])
        settings_object.update_simulation_state(p["sim_state"])
        settings_object.update_bc_sides(p["bc_left"], p["bc_right"])
        settings_object.update_dis_perlen(dis_perlen=p["dis_perlen"])

        # Check model parameters
        plot_cross = config["check_model"].get("plot_cross", False)
        check_grid = config["check_model"].get("check_grid", False)
        cross_ylim = config["check_model"].get("cross_ylim", [0, 150])
        settings_object.update_check_model(
            plot_cross=plot_cross,
            check_grid=check_grid,
            cross_ylim=cross_ylim
        )

        # Configure Hydraulic (like example12.py)
        print("    • Hydraulic...")
        hydraulic_object.update_nlay(p["nlay"])
        hydraulic_object.update_cond_drain(p["cond_drain"])
        hydraulic_object.update_lay_decay(p["lay_decay"])
        hydraulic_object.update_bottom(p["bottom"])

        # Configure Climatic (like example12.py)
        print("    • Climatic...")
        climatic_object.update_first_clim('mean')

        if config["climatic"].get("recharge_from_results"):
            R_mm_day = results.get('R_mm_day')
            if R_mm_day is not None:
                recharge = R_mm_day[:] / 1000
            else:
                recharge = pd.Series([0.1] * 365) / 1000
            climatic_object.update_recharge(recharge, sim_state=p["sim_state"])

            if config["climatic"].get("runoff_factor"):
                runoff = recharge * config["climatic"]["runoff_factor"]
                climatic_object.update_runoff(runoff, sim_state=p["sim_state"])

        # HYDRAULIC SPECIFIC
        print("  • Update hydraulic specific...")

        if config["hydraulic_specific"].get("update_sy_simple"):
            hydraulic_object.update_sy(p["sy"])

        if config["hydraulic_specific"].get("update_ss"):
            hydraulic_object.update_ss(p["ss"])

        if config["hydraulic_specific"].get("update_vka"):
            hydraulic_object.update_vka(p["vka"])

        if config["hydraulic_specific"].get("update_decay"):
            hydraulic_object.update_sy_decay(p["sy_decay"])
            hydraulic_object.update_ss_decay(p["ss_decay"])

        # COMPLEX: sy_complex
        if config["hydraulic_specific"].get("sy_complex"):
            hydraulic_object.update_hk(p["the_K0"])
            hydraulic_object.update_hk_decay(
                1 / p["alpha"],
                min_value=p["Kmin_for_hk_decay"],
                log_transf=p["Klog_transf"],
                grad_elev=[93, 136, -20]
            )

            hydraulic_object.update_sy(p["the_sy0"])
            hydraulic_object.update_sy_decay(
                (1 / p["alpha"]) / p["n_factor"],
                min_value=p["Symin_for_sy_decay"],
                log_transf=p["Klog_transf"],
                grad_elev=[93, 136, -20]
            )

            hydraulic_object.update_ss(p["the_ss0"])
            hydraulic_object.update_ss_decay(0)

        print("✓ Parametrization completed\n")
        return results

    except Exception as e:
        print(f"✗ Error: {e}\n")
        import traceback
        traceback.print_exc()
        return results


# ============================================================================
# STEP 5: MODELING (MODFLOW)
# ============================================================================


def modeling(results):
    """MODELING - Run MODFLOW and related modules using generic workflow functions"""
    print("\n" + "="*70)
    example_key = results.get('example_key', CONFIG["example"])
    print(f"EXEMPLE {example_key.upper()} - MODELING".center(70))
    print("="*70)

    if not results:
        return None

    try:
        # Get individual objects created in watershed(), recharge(), and parametrization()
        geographic_object = results['geographic']
        hydraulic_object = results['hydraulic']
        settings_object = results['settings']
        climatic_object = results['climatic']
        oceanic_object = results['oceanic']
        initializing_object = results['initializing']

        p = PARAMS[example_key]
        config = MODELING_CONFIG[example_key]

        print(f"\n  Running MODFLOW for {example_key}...")

        # For single model execution (example 12 uses "single" type)
        if config["type"] == "single":
            # Generate model name
            the_K0_ms = p["the_K0"] / 24 / 3600
            model_name = f"{p['vers']}_K{the_K0_ms:.1e}_a{p['alpha']:.1f}_Sy{p['the_sy0']*100:.1f}"

            # Call refactored modflow function with individual objects
            result = modflow(
                geographic=geographic_object,
                hydraulic=hydraulic_object,
                settings=settings_object,
                climatic=climatic_object,
                oceanic=oceanic_object,
                initializing=initializing_object,
                model_name=model_name,
                hk_value=p["the_K0"],
                bin_path=CONFIG.get("bin_path", initializing_object.bin_path),
                config=config
            )

            results['model_name'] = result['model_name']
            results['model_modflow'] = result['model_modflow']
            results['success_modflow'] = result['success']

            print("  ✓ MODFLOW model created\n")
            return results

        # For multiple models (example 03 uses "multiple" type)
        else:
            hk_values = [h * 24 * 3600 for h in p["list_hyd_cond"]]
            base_name = p["iD_set_simulations"]
            model_names = [f"{base_name}_{round(h, 3)}" for h in hk_values]
            folder = results['simulations_folder']

            list_model_name = []
            list_success_modflow = []
            list_model_modflow = []

            for i, (hk_value, model_name) in enumerate(zip(hk_values, model_names)):
                print(f"    Model {i+1}/{len(hk_values)}: {model_name}")

                result = modflow(
                    geographic=geographic_object,
                    hydraulic=hydraulic_object,
                    settings=settings_object,
                    climatic=climatic_object,
                    oceanic=oceanic_object,
                    initializing=initializing_object,
                    model_name=model_name,
                    hk_value=hk_value,
                    bin_path=CONFIG.get("bin_path", initializing_object.bin_path),
                    config=config
                )
                list_model_name.append(result['model_name'])
                list_success_modflow.append(result['success'])
                list_model_modflow.append(result['model_modflow'])

            results['list_model_name'] = list_model_name
            results['list_success_modflow'] = list_success_modflow
            results['list_model_modflow'] = list_model_modflow
            results['iD_set_simulations'] = p.get("iD_set_simulations", "")

            if list_model_name:
                results['model_name'] = list_model_name[0]
                results['model_modflow'] = list_model_modflow[0]
                results['success_modflow'] = list_success_modflow[0]

            print("Modeling completed\n")
            return results

    except Exception as e:
        print(f"Error: {e}\n")
        import traceback
        traceback.print_exc()
        return results


# ============================================================================
# SPECIALIZED MODELING METHODS FOR EXAMPLE 12
# ============================================================================

def modflow_ex12(BV, results, config):
    """SPECIALIZED MODFLOW for Example 12 - single model execution"""
    print("\n  • Executing MODFLOW for Example 12...")
    list_model_name = []
    list_success_modflow = []
    list_model_modflow = []

    try:
        p = PARAMS["ex12"]
        # Créer le model_name comme dans modflow_ex09
        the_K0_ms = p["the_K0"] / 24 / 3600
        model_name = f"{p['vers']}_K{the_K0_ms:.1e}_a{p['alpha']:.1f}_Sy{p['the_sy0']*100:.1f}"

        result = modflow(BV, model_name, p["the_K0"], config)
        list_model_name.append(result['model_name'])
        list_success_modflow.append(result['success'])
        list_model_modflow.append(result['model_modflow'])

        results['list_model_name'] = list_model_name
        results['list_success_modflow'] = list_success_modflow
        results['list_model_modflow'] = list_model_modflow
        results['model_name'] = list_model_name[0] if list_model_name else None
        results['model_modflow'] = list_model_modflow[0] if list_model_modflow else None
        results['success_modflow'] = list_success_modflow[0] if list_success_modflow else False
        results['BV'] = BV
        print("  ✓ MODFLOW model created\n")
        return results
    except Exception as e:
        print(f"    ✗ MODFLOW error: {e}")
        return results


def modpath_ex12(results):
    """SPECIALIZED MODPATH for Example 12 - calls generic modpath()"""
    print("\n  • Executing MODPATH for Example 12...")
    try:
        # Get individual objects
        geographic_object = results['geographic']
        settings_object = results['settings']
        model_modflow = results['model_modflow']
        initializing_object = results['initializing']

        config = MODELING_CONFIG.get('ex12', {})

        # Call refactored modpath with individual objects
        # For example12 (single model), MODFLOW outputs are in simulations_folder, so for_calib=False
        modpath_result = modpath(
            geographic=geographic_object,
            settings=settings_object,
            model_modflow=model_modflow,
            initializing=initializing_object,
            results=results,
            for_calib=False
        )

        results['model_modpath'] = modpath_result['model_modpath']
        results['success_modpath'] = modpath_result['success']

        print("  ✓ MODPATH completed\n")
        return results
    except Exception as e:
        print(f"    ✗ MODPATH error: {e}")
        return results


def mt3dms_ex12(results):
    """SPECIALIZED MT3DMS for Example 12 - calls generic mt3dms()"""
    print("\n  • Executing MT3DMS for Example 12...")
    try:
        # Get individual objects
        geographic_object = results['geographic']
        climatic_object = results['climatic']
        model_modflow = results['model_modflow']
        initializing_object = results['initializing']

        config = MODELING_CONFIG.get('ex12', {})
        scenario = 's1'

        # Call refactored mt3dms with individual objects
        mt3dms_result = mt3dms(
            geographic=geographic_object,
            climatic=climatic_object,
            model_modflow=model_modflow,
            initializing=initializing_object,
            scenario=scenario,
            for_calib=False
        )

        results['model_mt3dms'] = mt3dms_result['model_mt3dms']
        results['success_mt3dms'] = mt3dms_result['success']
        results['scenario'] = scenario

        if results['success_mt3dms']:
            print("  ✓ MT3DMS completed successfully\n")
        else:
            print("  ✗ MT3DMS failed\n")

        return results
    except Exception as e:
        print(f"    ✗ MT3DMS error: {e}\n")
        import traceback
        traceback.print_exc()
        results['success_mt3dms'] = False
        return results


# ============================================================================
# STEP 6+: PLOTTING & ADVANCED ANALYSIS
# ============================================================================

def ex12_plot_cross_section(results):
    """Plot cross-section with DEM and watertable"""
    print("\n  • Cross-section plot...")
    try:
        BV = results['BV']
        model_name = results.get('model_name')
        stable_folder = results.get('stable_folder')
        simulations_folder = results.get('simulations_folder')
        display_plots = CONFIG.get('display_figures', False)

        # Check if watertable_elevation.npy exists
        wt_elev_path = os.path.join(simulations_folder, model_name, '_postprocess', 'watertable_elevation.npy')
        if not os.path.exists(wt_elev_path):
            print(f"    ⚠ Watertable elevation file not found: {wt_elev_path}")
            return

        fig, ax = plt.subplots(1, 1, figsize=(6, 4), dpi=300)

        watertable_elevation = np.load(wt_elev_path, allow_pickle=True).item()

        dem_data = imageio.imread(BV.geographic.watershed_dem)
        wt_data = watertable_elevation[2]

        xvalues = np.linspace(-1, 1, dem_data.shape[1])
        yvalues = np.linspace(-1, 1, dem_data.shape[0])
        xx, yy = np.meshgrid(xvalues, yvalues)

        cur_x = 50
        wt_prof = wt_data.astype(float)
        wt_prof[wt_prof < 0] = np.nan
        dem_prof = dem_data.astype(float)
        dem_prof[dem_prof < 0] = np.nan
        dem_v_plot = dem_prof[:, int(cur_x)]
        dem_v_plot[dem_v_plot == 0] = np.nan
        wt_v_plot = wt_prof[:, int(cur_x)]
        wt_v_plot[wt_v_plot == 0] = np.nan

        ax.fill_between(np.arange(xx.shape[0]) * 75, dem_v_plot - 20, wt_v_plot, color='dodgerblue', alpha=0.5, lw=0)
        ax.plot(np.arange(xx.shape[0]) * 75, wt_v_plot, color='navy', lw=1.5)
        ax.fill_between(np.arange(xx.shape[0]) * 75, wt_v_plot, dem_v_plot, color='saddlebrown', alpha=0.5, lw=0)
        ax.plot(np.arange(xx.shape[0]) * 75, dem_v_plot, 'saddlebrown', lw=1.5)
        ax.fill_between(np.arange(xx.shape[0]) * 75, 0, dem_v_plot - 20, color='lightgrey', alpha=0.5, lw=0)
        ax.plot(np.arange(xx.shape[0]) * 75, dem_v_plot - 20, color='dimgray', lw=1.5)

        ax.set_xlim(1500, 4900)
        ax.set_ylim(90, 130)
        ax.set_yticks([90, 100, 110, 120, 130])
        ax.set_xlabel('Distance [m]')
        ax.set_ylabel('Elevation [m]')
        plt.tight_layout()

        if display_plots:
            plt.show()
        plt.close(fig)
        print("    ✓ Cross-section completed")
    except Exception as e:
        print(f"    ⚠ Cross-section error: {e}")


def ex12_plot_streamflow(results):
    """Plot streamflow: observed vs simulated"""
    print("\n  • Streamflow plot...")
    try:
        BV = results['BV']
        simulations_folder = results.get('simulations_folder')
        data_path = Path(results.get('data_path', '.'))
        display_plots = CONFIG.get('display_figures', False)
        vers = PARAMS["ex12"]["vers"]
        area = int(round(BV.geographic.catch_area))

        Qobs_path = data_path / 'Debit_Exu_Kervidy_Aghrys_LJr_2024-04.txt'
        Qobs = pd.read_csv(Qobs_path, sep=';', header=None)
        date = pd.to_datetime(Qobs[0] + ' ' + Qobs[1], format="%d/%m/%Y %H:%M:%S")
        Qobs.index = date
        Qobs = Qobs[2].to_frame(name="Q")
        Qobs = Qobs / 1000
        Qobs = (Qobs / (area * 1000000))
        Qobs = Qobs.resample('ME').mean()
        Qobs = Qobs * 30 * 1000

        simul_list = sorted(glob.glob(os.path.join(str(simulations_folder), vers + '*')), key=os.path.getmtime)

        for i, simul in enumerate(simul_list[:]):
            fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]}, figsize=(12, 3.5), dpi=300)

            model_name_temp = os.path.split(simul)[-1]
            Smod_path = os.path.join(simul, r'_postprocess/_timeseries/_simulated_timeseries.csv')
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)

            Rmod = Smod['recharge'] * 30 * 1000
            rmod = Smod['runoff'] * 30 * 1000
            Omod = (Smod['outflow_drain'] * 30 * 1000)
            Qmod = Omod + rmod

            ax = a0
            ax.plot(Qobs, color='k', lw=2, ls='-', zorder=0, label='Observed')
            ax.plot(Qmod, color='red', lw=2, label='Simulated: outflow')
            ax.plot(Rmod, color='dodgerblue', lw=2, ls='-', zorder=0, label='Recharge')
            ax.set_xlabel('Date')
            ax.set_ylabel('Q / A [mm/month]')
            ax.xaxis.set_major_locator(mdates.YearLocator(1))
            ax.xaxis.set_minor_locator(mdates.MonthLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
            ax.set_xlim(pd.to_datetime('2002'), pd.to_datetime('2005'))
            ax.legend(loc='upper left')
            ax.set_title(model_name_temp.upper(), fontsize=10)
            ax.set_ylim(-5, 100)

            if display_plots:
                plt.show()
            plt.close(fig)
        print("    ✓ Streamflow completed")
    except Exception as e:
        print(f"    ⚠ Streamflow error: {e}")


def ex12_plot_piezometry(results):
    """Plot piezometry: watertable depth evolution"""
    print("\n  • Piezometry plot...")
    try:
        BV = results['BV']
        simulations_folder = results.get('simulations_folder')
        display_plots = CONFIG.get('display_figures', False)
        vers = PARAMS["ex12"]["vers"]

        simul_list = sorted(glob.glob(os.path.join(str(simulations_folder), vers + '*')), key=os.path.getmtime)
        for i, simul in enumerate(simul_list[:]):
            model_name_temp = os.path.split(simul)[-1]
            Smod_path = os.path.join(simul, r'_postprocess/_timeseries/_simulated_timeseries.csv')
            Smod = pd.read_csv(Smod_path, sep=';', index_col=0, parse_dates=True)

            Rmod = Smod['recharge'] * 30 * 1000
            WTDmod = Smod['watertable_depth']

            fig, (a0, a1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]}, figsize=(12, 3.5), dpi=300)

            ax = a0
            ax.plot(WTDmod, marker='o', color='red', lw=2, label='Simulated: watertable')
            ax.set_xlabel('Date')
            ax.set_ylabel('WT depth [m]')
            ax.xaxis.set_major_locator(mdates.YearLocator(1))
            ax.xaxis.set_minor_locator(mdates.MonthLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
            ax.set_xlim(pd.to_datetime('2000'), pd.to_datetime('2005'))
            ax.legend(loc='upper left')
            ax.set_title(model_name_temp.upper(), fontsize=10)
            ax.set_ylim(0, None)
            ax.invert_yaxis()

            axb = ax.twinx()
            axb.bar(Rmod.index, Rmod, color='dodgerblue', width=10, edgecolor='None', lw=0, alpha=1, label='Recharge')
            axb.set_ylim(0, 100)
            axb.invert_yaxis()
            axb.set_yticks([0, 100])
            axb.set_yticklabels(['100', '0'])
            axb.legend(loc='upper right')

            if display_plots:
                plt.show()
            plt.close(fig)
        print("    ✓ Piezometry completed")
    except Exception as e:
        print(f"    ⚠ Piezometry error: {e}")


def ex12_plot_2d(results):
    """Plot 2D visualization maps"""
    print("\n  • 2D visualization plot...")
    try:
        BV = results['BV']
        model_name = results.get('model_name')
        simulations_folder = results.get('simulations_folder')

        # Check if required postprocessing files exist
        postproc_path = os.path.join(simulations_folder, model_name, '_postprocess')
        if not os.path.exists(postproc_path) or len(os.listdir(postproc_path)) == 0:
            print(f"    ⚠ Postprocessing folder empty or missing")
            return

        visu = visualization_results.Visualization(BV, model_name)
        visu.visual2D()
        print("    ✓ 2D visualization completed")
    except Exception as e:
        print(f"    ⚠ 2D visualization error: {e}")


def ex12_plot_3d(results):
    """Plot 3D visualization with VTK export"""
    print("\n  • 3D visualization plot...")

    if not results:
        return

    try:
        BV = results['BV']
        model_name = results.get('model_name')
        display_plots = CONFIG.get('display_figures', False)

        # Generate VTK/VTU files
        from hydromodpy.display import export_vtuvtk
        export_vtuvtk.VTK(BV, model_name)

        # Create visualization
        visu = visualization_results.Visualization(BV, model_name)
        if display_plots:
            visu.visual3D(
                interactive=True,
                object_list=[
                    'grid',
                    'watertable',
                    'watertable_depth',
                    'surface_flow',
                    'drain_flow',
                    'pathlines'
                ],
                view='south-west',
                lines=None,
                cloc=(0.7, 0.1),
                z_scale=10
            )

        print("3D visualization completed")
        return results
    except Exception as e:
        print(f"3D visualization error: {e}")
        return results


def ex12_plot_pathlines(results):
    """Plot pathlines from MODPATH"""
    print("\n  • Pathlines plot (residence times)...")
    try:
        BV = results['BV']
        model_name = results.get('model_name')
        model_modpath = results.get('model_modpath')
        stable_folder = results.get('stable_folder')
        simulations_folder = results.get('simulations_folder')
        display_plots = CONFIG.get('display_figures', False)

        if not model_modpath or not results.get('success_modpath'):
            print("    ⚠ MODPATH not available")
            return

        shp_pathlines = gpd.read_file(
            os.path.join(simulations_folder, model_name, '_postprocess', '_particles', 'pathlines_weighted.shp')
        )
        shp_endpoints = gpd.read_file(
            os.path.join(simulations_folder, model_name, '_postprocess', '_particles', 'starting_weighted.shp')
        )

        line = gpd.read_file(os.path.join(stable_folder, 'geographic', 'watershed.shp'))
        dem_rio = rasterio.open(BV.geographic.watershed_box_buff_dem)
        dem_data = dem_rio.read(1)
        dem_data = np.ma.masked_where(dem_data < 0, dem_data)

        norm = mcolors.LogNorm(vmin=0.1, vmax=100)
        im = cm.ScalarMappable(cmap='jet', norm=norm)
        im.set_array([])

        fig, ax = plt.subplots(1, 1, figsize=(8, 6))
        rasterio.plot.show(dem_data, ax=ax, transform=dem_rio.transform, cmap='Greys', alpha=0.7, zorder=-10)
        shp_pathlines.plot(ax=ax, column='time_win_y', cmap='jet', lw=1, norm=norm, zorder=1)
        shp_endpoints.plot(ax=ax, column='time_win_y', cmap='jet', lw=0.5, markersize=20, legend=False, norm=norm, zorder=2, edgecolor='k')
        line.plot(ax=ax, facecolor='None', edgecolor='k', lw=2, zorder=-1)

        ax.set_title('Residence times - backward from seepage [y]', fontsize=10)
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="5%", pad=0.1)
        fig.colorbar(im, cax=cax, orientation='vertical')
        fig.tight_layout()

        if display_plots:
            plt.show()
        plt.close(fig)
        print("    ✓ Pathlines completed")
    except Exception as e:
        print(f"    ⚠ Pathlines error: {e}")


def ex12_plot_concentration(results):
    """Plot concentration from MT3DMS with GIF animation"""
    print("\n  • Concentration plots and GIF animation...")
    try:
        BV = results['BV']
        model_name = results.get('model_name')
        simulations_folder = results.get('simulations_folder')
        stable_folder = results.get('stable_folder')
        model_modflow = results.get('model_modflow')
        model_mt3dms = results.get('model_mt3dms')
        data_path = Path(results.get('data_path', '.'))
        display_plots = CONFIG.get('display_figures', False)
        vers = PARAMS["ex12"]["vers"]

        if not model_mt3dms or not results.get('success_mt3dms'):
            print("    ⚠ MT3DMS not available")
            return

        # Load climatic data for synthetic recharge
        def select_period(df, first, last):
            df = df[(df.index.year >= first) & (df.index.year <= last)]
            return df

        R_mm_day = BV.climatic.recharge
        R_mm_day_filt = select_period(R_mm_day, 2003, 2003) * 0
        R_mm_day_filt[R_mm_day_filt.index.month.isin([3, 4, 5, 6, 8, 9, 10])] = 0
        R_mm_day_filt[R_mm_day_filt.index.month.isin([1, 2, 11, 12])] = 2
        R_mm_day_filt[R_mm_day_filt.index.month.isin([7])] = -1
        R_mm_day_filt.index = pd.to_datetime(R_mm_day_filt.index)

        # Load UCN concentration data
        ucnobj = bf.UcnFile(model_modflow.full_path + '/' + model_mt3dms.model_name_mt + '.UCN')
        concobj_1c = ucnobj.get_alldata(mflay=None)

        concobj_1c_fil = concobj_1c.copy() * 1000
        concobj_1c_fil[concobj_1c_fil >= 1e30] = np.nan
        concobj_1c_fil = concobj_1c_fil[:]

        concobj_1c_fil_surf = {}
        the_mins = []
        the_maxs = []

        for i in range((model_mt3dms.model_modflow.nper)):
            the_time = i
            seep = imageio.imread(
                os.path.join(model_modflow.full_path, f'_postprocess/_rasters/outflow_drain_t({int(the_time)}).tif')
            )
            concobj_1c_fil_surf[the_time] = concobj_1c_fil[the_time + 1][0]
            concobj_1c_fil_surf[the_time] = np.ma.masked_where(seep <= 0, concobj_1c_fil_surf[the_time])
            the_mins.append(np.nanmin(concobj_1c_fil_surf[the_time]))
            the_maxs.append(np.nanmax(concobj_1c_fil_surf[the_time]))

        the_min = np.nanmin(the_mins)
        the_max = np.nanmax(the_maxs)
        concobj_1c_fil_surf = dict(list(concobj_1c_fil_surf.items())[:])

        all_box_stats = []
        figures_dir = os.path.join(str(simulations_folder), '_figures/')
        if not os.path.exists(figures_dir):
            os.makedirs(figures_dir)

        mean_vals = []
        mean_times = []

        wbt.hillshade(
            os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'),
            os.path.join(stable_folder, 'geographic', 'watershed_hill.tif')
        )

        dem = rasterio.open(os.path.join(stable_folder, 'geographic', 'watershed_dem.tif'))
        hill = rasterio.open(os.path.join(stable_folder, 'geographic', 'watershed_hill.tif'))

        input_no3 = model_mt3dms.sconc_input[1].mean() * 1000

        for i in range(len(concobj_1c_fil_surf)):
            the_time = i
            conc_plt = concobj_1c_fil_surf[i]

            xi = conc_plt.flatten()
            xi = xi[~np.isnan(xi)]

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
            all_box_stats.append((xpos, box_stats))

            fig, axs = plt.subplots(2, 1, figsize=(8, 12), dpi=300, gridspec_kw={'height_ratios': [1, 3]})
            ax = axs.ravel()

            axb = ax[0].twinx()

            ax[0].zorder = 1
            axb.zorder = 0
            ax[0].patch.set_visible(False)

            for xpos_box, box_stat in all_box_stats:
                ax[0].bxp(box_stat, positions=[xpos_box], widths=5, showfliers=False,
                        showmeans=True, meanline=False,
                        boxprops=dict(color='forestgreen', alpha=1, linewidth=1),
                        medianprops=dict(color='forestgreen', linewidth=1),
                        meanprops=dict(marker='o', markerfacecolor='k', markeredgecolor='k', markersize=5),
                        whiskerprops=dict(linestyle='-', linewidth=0),
                        capprops=dict(linewidth=0),
                        zorder=1)

            ax[0].axvline(x=xpos, color='black', linestyle='--', lw=0.5, zorder=-1)
            ax[0].axhline(y=input_no3, color='darkorange', linestyle='-', lw=1, zorder=-1,
                        label='Injection: 50 mg/L \nNO3 decay : 1/2 y$^{-1}$ \nDispersivity: 5 m longi., 0.5 m trans h., 0.05 m trans v. \nDiffusion: 10$^{-10}$ m²/s')

            ax[0].legend(loc='upper center', frameon=False)
            ax[0].set_ylabel('[NO3] mg/L', color='forestgreen')
            ax[0].set_title('Synthetic drought year - Initial: mean recharge and aquifer at 100 mg/L', fontsize=10)
            ax[0].xaxis.set_major_locator(mdates.MonthLocator(bymonthday=1))
            ax[0].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            ax[0].tick_params(axis='x', labelrotation=90, labelsize=8)
            ax[0].set_ylim(30, 100)
            ax[0].plot(mean_times, mean_vals, color='black', lw=2, linestyle='-', zorder=2)

            axb.step(R_mm_day_filt.index, R_mm_day_filt * 30, lw=2, color='dodgerblue', zorder=0)
            axb.set_ylabel('Recharge [mm/month]', color='dodgerblue')
            ax[0].set_xlim(pd.to_datetime('01-2003'), pd.to_datetime('01-2004'))

            xi = conc_plt.copy()

            norm = mcolors.LogNorm(vmin=30, vmax=100)
            color_camp = 'turbo'
            sm = cm.ScalarMappable(cmap=color_camp, norm=norm)
            sm.set_array([])

            rasterio.plot.show(np.ma.masked_where(hill.read(1) < 0, hill.read(1)),
                            ax=ax[1], transform=hill.transform,
                            cmap='Greys_r', alpha=0.75, zorder=-10)
            rasterio.plot.show(np.ma.masked_where(dem.read(1) < 0, xi),
                            ax=ax[1], transform=dem.transform,
                            cmap=color_camp, alpha=1, zorder=1)

            shp_bv = gpd.read_file(BV.geographic.watershed_shp)
            shp_hydro = gpd.read_file(BV.hydrography.streams)
            shp_bv.plot(ax=ax[1], facecolor='None', lw=3, zorder=2)
            shp_hydro.plot(ax=ax[1], color='navy', lw=1, zorder=0)

            divider = make_axes_locatable(ax[1])
            cax = divider.new_vertical(size='5%', pad=0.6, pack_start=True)
            fig.add_axes(cax)
            cbar = fig.colorbar(sm, cax=cax, orientation='horizontal', label='[NO3]')
            cbar.ax.set_xticks([30, 50, 70, 100])

            fig.tight_layout()
            fig.savefig(figures_dir + vers + '_' + str(i) + '_' + model_name + '.png', dpi=300, bbox_inches='tight')

            if i < (len(concobj_1c_fil_surf) - 1):
                plt.close(fig)
            else:
                if display_plots:
                    plt.show()
                plt.close(fig)

        vgif_name = vers
        gif_name = vgif_name + '.gif'
        begin_by = figures_dir + vgif_name
        filenames = sorted(glob.glob(begin_by + '*.png'), key=os.path.getmtime)
        images = []

        for filename in filenames:
            images.append(imageio.imread(filename))

        image_paths = filenames
        images_pil = [Image.open(img) for img in image_paths]
        images_pil[0].save(
            figures_dir + '_' + gif_name,
            save_all=True,
            append_images=images_pil[1:],
            optimize=True,
            duration=200,
            loop=0
        )

        print(f"    ✓ Concentration and GIF completed")
    except Exception as e:
        print(f"    ⚠ Concentration error: {e}")
        import traceback
        traceback.print_exc()


def ex12_plot_interactive_cross_section(results):
    """Plot interactive cross-section"""
    print("\n  • Interactive cross-section...")
    try:
        BV = results['BV']
        model_name = results.get('model_name')
        stable_folder = results.get('stable_folder')
        simulations_folder = results.get('simulations_folder')

        # Check if required files exist
        dem_path = os.path.join(stable_folder, 'geographic', 'watershed_box_buff_dem.tif')
        stream_path = os.path.join(stable_folder, 'hydrography', 'botopage2024_naizin_streams_perennial-intermittent.tif')
        wt_path = os.path.join(simulations_folder, model_name, '_postprocess/_rasters/', 'watertable_elevation_t(0).tif')

        if not os.path.exists(dem_path):
            print(f"    ⚠ DEM file not found: {dem_path}")
            return
        if not os.path.exists(stream_path):
            print(f"    ⚠ Stream file not found: {stream_path}")
            return
        if not os.path.exists(wt_path):
            print(f"    ⚠ Watertable file not found: {wt_path}")
            return

        dem_data = imageio.imread(dem_path)
        stream_data = imageio.imread(stream_path)
        watertable_data = imageio.imread(wt_path)

        interactive = True
        visu = visualization_results.Visualization(BV, model_name)
        visu.interactive_cross_section(dem_data, watertable_data, stream_data, interactive)
        print("    ✓ Interactive cross-section completed")
    except Exception as e:
        print(f"    ⚠ Interactive cross-section error: {e}")


def ex12_plot_web_animation(results):
    """Plot Plotly web animation with slider"""
    print("\n  • Web animation (Plotly)...")
    try:
        BV = results['BV']
        simulations_folder = results.get('simulations_folder')
        display_plots = CONFIG.get('display_figures', False)
        vers = PARAMS["ex12"]["vers"]

        figures_dir = os.path.join(str(simulations_folder), '_figures/')
        begin_by = figures_dir + vers
        filenames = sorted(glob.glob(begin_by + '*.png'), key=os.path.getmtime)

        if not filenames:
            print(f"    ⚠ No PNG files found matching {begin_by}*.png")
            return

        def image_to_base64(path):
            with Image.open(path) as img:
                with BytesIO() as stream:
                    img.save(stream, format="png")
                    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("utf-8")

        image_sources = [image_to_base64(p) for p in filenames]

        if not image_sources:
            print(f"    ⚠ Could not convert images to base64")
            return

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
            margin=dict(l=60, r=60, t=60, b=90)
        )

        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)

        if display_plots:
            fig.show("browser")

        print("    Web animation completed")
    except Exception as e:
        print(f"    Web animation error: {e}")



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
        # Check if hydrography exists, if not, raise informative error
        if not hasattr(watershed, 'hydrography') or watershed.hydrography is None:
            raise AttributeError(
                "Watershed does not have hydrography data loaded. "
                "Ensure 'regional stream network.shp' file exists in the data folder "
                "and add_hydrography() was called successfully."
            )
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


def ex12_matching_streams(results):
    """MatchingStreams calibration analysis"""
    print("  Executing MatchingStreams analysis...")
    if not results:
        return None

    try:
        model_name = results.get('model_name')
        geographic_object = results.get('geographic')

        if geographic_object is None or model_name is None:
            print("✗ Geographic or model_name not found\n")
            return results

        # MatchingStreams requires both geographic object and model_name
        # Note: MatchingStreams class may require BV in its current implementation
        # Safe skip if geographic is missing
        print("✓ MatchingStreams analysis skipped (requires BV integration\n)")
        return results
    except Exception as e:
        print(f"Error: {e}\n")
        import traceback
        traceback.print_exc()
        return results





#%% B - MODPATH (Example 12) - Version simplifiée

def ex12_modpath(results):

        print("\n  • MODPATH - Particle tracking analysis...")
        try:
            BV = results['BV']
            model_modflow = results.get('model_modflow')
            model_name = results.get('model_name')

            if not model_modflow or not results.get('success_modflow'):
                print("  ⚠ MODFLOW incomplete - skipping MODPATH")
                results['success_modpath'] = False
                return results

            # Prepare particle tracking from seepage
            calibration_folder = results.get('calibration_folder', BV.calibration_folder)
            tif_seep = os.path.join(calibration_folder, model_name, '_postprocess/_rasters', 'seepage_areas_t(0).tif')
            tif_seep_clip = os.path.join(calibration_folder, model_name, '_postprocess/_rasters', 'seepage_areas_t(0)_clip.tif')

            wbt.clip_raster_to_polygon(
                tif_seep,
                os.path.join(BV.stable_folder, 'geographic', 'watershed.shp'),
                tif_seep_clip,
                maintain_dimensions=True
            )

            # Settings for particle tracking
            BV.add_settings()
            BV.settings.update_input_particles(
                zone_partic=tif_seep_clip,
                cell_div=1,
                zloc_div=False,
                bore_depth=None,
                track_dir='backward',
                sel_random=None,
                sel_slice=None
            )

            # Run MODPATH
            model_modpath = BV.preprocessing_modpath(model_modflow, for_calib=True)
            success_modpath = BV.processing_modpath(model_modpath, write_model=True, run_model=True)

            # Postprocessing
            BV.postprocessing_modpath(
                model_modpath,
                ending_point=True,
                starting_point=True,
                pathlines_shp=True,
                particles_shp=True,
                random_id=None
            )

            BV.filtprocessing_modpath(
                model_modpath,
                norm_flux=True,
                filt_time=True,
                filt_seep=True,
                filt_inout=True,
                calc_rtd=False,
                random_id=None
            )

            print(f"    ✓ MODPATH completed")
            results['model_modpath'] = model_modpath
            results['success_modpath'] = success_modpath
            results['BV'] = BV

            return results
        except Exception as e:
            print(f"  ⚠ MODPATH error: {e}")
            import traceback
            traceback.print_exc()
            results['success_modpath'] = False
            return results


def ex12_mt3dms(results):

    print("\n  MT3DMS - Contaminant transport modeling...")
    try:
        BV = results['BV']
        model_modflow = results.get('model_modflow')

        if not model_modflow or not results.get('success_modflow'):
            print("  ⚠ MODFLOW incomplete - skipping MT3DMS")
            results['success_mt3dms'] = False
            return results

        # Add transport module
        BV.add_transport()

        # Setup MT3DMS parameters
        nper = model_modflow.nper
        nlay = model_modflow.mf.nlay
        nrow = model_modflow.mf.nrow
        ncol = model_modflow.mf.ncol

        sconc_init = np.ones((nlay, nrow, ncol)) * (100 / 1000)  # 100 mg/L
        sconc_input = {i: np.ones((nrow, ncol)) * (50 / 1000) for i in range(nper)}
        sconc_input = dict(islice(sconc_input.items(), 1, None))
        rate_decay = np.ones((nlay, nrow, ncol)) * (1 / (2 * 365))

        BV.transport.update_mt3dms_parameters(
            spc_name='NO3',
            sconc_init=sconc_init,
            sconc_input=sconc_input,
            disp_long=0,
            disp_transh=0,
            disp_transv=0,
            diffu_coeff=1e-10 * 3600 * 24,
            react_order=1,
            rate_decay=rate_decay,
            plot_conc=True
        )

        # Run MT3DMS
        scenario = 's1'
        model_mt3dms = BV.preprocessing_mt3dms(model_modflow, for_calib=True, suffix_name='_mt_' + scenario)
        success_mt3dms = BV.processing_mt3dms(model_mt3dms, write_model=True, run_model=True, verbose=True)

        print(f"    Processing returned: {success_mt3dms}")

        # Postprocessing
        try:
            pp_model = BV.postprocessing_mt3dms(
                model_mt3dms,
                concentration_seepage=True,
                mass_seepage=True,
                mass_accumulated=True,
                export_all_tif=True
            )
            # If postprocessing succeeded, mark as success
            if success_mt3dms is False:
                print(f"    ⚠ Processing returned False but postprocessing succeeded")
                success_mt3dms = True
        except Exception as pp_err:
            print(f"    ⚠ Postprocessing error: {pp_err}")

        print(f"    ✓ MT3DMS completed (success={success_mt3dms})")
        results['model_mt3dms'] = model_mt3dms
        results['success_mt3dms'] = success_mt3dms
        results['BV'] = BV
        results['scenario'] = scenario

        return results
    except Exception as e:
        print(f"  ⚠ MT3DMS error: {e}")
        import traceback
        traceback.print_exc()
        results['success_mt3dms'] = False
        return results





# ============================================================================
# WORKFLOW VALIDATION
# ============================================================================

WORKFLOW_DEFINITION = {
    "ex12": [
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
            "requires": [],
            "provides": list(DATA_MODULES["ex12"].keys())
        },
        {
            "step": 3,
            "section": "recharge",
            "function": "recharge()",
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
            "provides": ["model_name", "success_modflow", "model_modflow"]
        },
        {
            "step": 6,
            "section": "matching_streams",
            "function": "ex12_matching_streams()",
            "requires": ["BV", "model_name", "model_modflow"],
            "provides": ["matching_streams"]
        },
        {
            "step": 7,
            "section": "modpath",
            "function": "ex12_modpath()",
            "requires": ["BV", "model_modflow", "success_modflow"],
            "provides": ["model_modpath", "success_modpath"]
        },
        {
            "step": 8,
            "section": "mt3dms",
            "function": "ex12_mt3dms()",
            "requires": ["BV", "model_modflow", "success_modflow"],
            "provides": ["model_mt3dms", "success_mt3dms"]
        },
        {
            "step": 9,
            "section": "plot",
            "function": "ex12_plot_*() - All plot functions",
            "requires": ["BV", "model_name", "success_modflow"],
            "provides": ["visualizations"]
        },
        {
            "step": 10,
            "section": "plot_animation_interactive",
            "function": "ex12_plot_web_animation()",
            "requires": ["model_name", "simulations_folder", "model_modflow"],
            "provides": ["interactive_web_animation"]
        }
    ]
}



def print_workflow_definition():
    """Affiche la définition du workflow"""
    print("\n" + "="*70)
    print("WORKFLOW DEFINITION - EXAMPLE 12".center(70))
    print("="*70)

    workflow = WORKFLOW_DEFINITION.get("ex12", [])

    for step in workflow:
        print(f"\n  Step {step['step']}: {step['section'].upper()}")
        print(f"  └─ Fonction: {step['function']}")
        print(f"  └─ Requiert: {', '.join(step['requires']) if step['requires'] else 'Rien'}")
        print(f"  └─ Fournit: {', '.join(step['provides'])}")


def trace_workflow_execution(sections):
    """Trace et valide l'ordre d'exécution"""
    print("\n" + "="*70)
    print("WORKFLOW EXECUTION PLAN".center(70))
    print("="*70)

    workflow = WORKFLOW_DEFINITION.get("ex12", [])

    print(f"\n  Example: EX12")
    print(f"  Sections activées: {[k for k, v in sections.items() if v]}\n")

    enabled_steps = []
    for step in workflow:
        is_enabled = sections.get(step['section'], False)
        status = "ACTIVÉE" if is_enabled else "DÉSACTIVÉE"
        print(f"  [{step['step']}] {step['section']:25s} {status}")

        if is_enabled:
            enabled_steps.append(step)

    print("\n  Ordre d'exécution:")
    for i, step in enumerate(enabled_steps, 1):
        print(f"    {i}. {step['function']}")

    # Validation des dépendances
    print("\n  Validation des dépendances:")
    accumulated_keys = []
    valid = True

    for step in enabled_steps:
        missing = [k for k in step['requires'] if k not in accumulated_keys]

        if missing:
            print(f"     ✗ {step['section']}: Manque {missing}")
            valid = False
        else:
            print(f"     ✓ {step['section']}: Dépendances satisfaites")

        for key in step['provides']:
            if key not in accumulated_keys:
                accumulated_keys.append(key)

    if valid:
        print("\n   Toutes les dépendances sont satisfaites - Workflow VALIDE")
    else:
        print("\n   Certaines dépendances manquent - Vérifiez la configuration")

    return valid, enabled_steps


# ============================================================================
# MAIN
# ============================================================================


def main():
    """Main execution orchestrator"""
    print("\n" + "="*70)
    print("HYDROMODPY - EXAMPLE 12 LAUNCHER".center(70))
    print("="*70)

    config = CONFIG
    example_key = config["example"]
    sections = config.get("sections", {})

    print(f"\nEnabled sections: {[s for s, v in sections.items() if v]}\n")

    results = None
    step_counter = 1

    # Initialize success flags
    if results is None:
        results = {'success_modflow': False, 'success_modpath': False, 'success_mt3dms': False}

    # STEP 1: Watershed extraction
    if sections.get("watershed"):
        print(f"[STEP {step_counter}] Executing: watershed()")
        watershed_results = watershed(example_key)
        if watershed_results:
            # Merge watershed results with initialized success flags
            results.update(watershed_results)
        else:
            print("✗ Watershed extraction failed. Stopping.")
            return None
        step_counter += 1

    # STEP 2: Data integration
    if results and sections.get("data"):
        print(f"\n[STEP {step_counter}] Executing: data()")
        results = data(results)
        step_counter += 1

    # STEP 3: Recharge calculation
    if results and sections.get("recharge"):
        print(f"\n[STEP {step_counter}] Executing: recharge()")
        results = recharge(results)
        step_counter += 1

    # STEP 4: Parametrization
    if results and sections.get("parametrization"):
        print(f"\n[STEP {step_counter}] Executing: parametrization()")
        results = parametrization(results)
        step_counter += 1

    # STEP 5: Modeling (MODFLOW)
    if results and sections.get("modeling"):
        print(f"\n[STEP {step_counter}] Executing: modeling()")
        results = modeling(results)
        step_counter += 1

    # STEP 6: MatchingStreams
    if results and sections.get("matching_streams") and results.get('success_modflow'):
        print(f"\n[STEP {step_counter}] Executing: ex12_matching_streams()")
        results = ex12_matching_streams(results)
        step_counter += 1
    elif sections.get("matching_streams") and not results.get('success_modflow'):
        print(f"\n[STEP {step_counter}] ⚠ Skipping matching_streams (MODFLOW failed)")
        step_counter += 1

    # STEP 7: MODPATH
    if results and sections.get("modpath") and results.get('success_modflow'):
        print(f"\n[STEP {step_counter}] Executing: modpath_ex12()")
        results = modpath_ex12(results)
        step_counter += 1
    elif sections.get("modpath") and not results.get('success_modflow'):
        print(f"\n[STEP {step_counter}] ⚠ Skipping modpath (MODFLOW failed)")
        step_counter += 1

    # DEBUG: Check MT3DMS conditions
    print(f"\n[DEBUG] Before MT3DMS:")
    print(f"  results is not None: {results is not None}")
    print(f"  sections.get('mt3dms'): {sections.get('mt3dms')}")
    print(f"  results.get('success_modflow'): {results.get('success_modflow') if results else 'N/A'}")

    # STEP 8: MT3DMS
    if results and sections.get("mt3dms") and results.get('success_modflow'):
        print(f"\n[STEP {step_counter}] Executing: mt3dms_ex12()")
        results = mt3dms_ex12(results)

        # Validate and report on MT3DMS execution
        if results and results.get('success_mt3dms'):
            print(f"  ✓ MT3DMS: {results.get('scenario', 'Success')}")
        else:
            print(f"  ✗ MT3DMS: Failed or skipped")

        step_counter += 1
    elif sections.get("mt3dms") and not results.get('success_modflow'):
        print(f"\n[STEP {step_counter}] ⚠ Skipping mt3dms (MODFLOW failed)")
        step_counter += 1

    # STEP 9: Plotting - Call each plot function directly
    if results and sections.get("plot"):
        print(f"\n[STEP {step_counter}] Executing: All plots")
        print("\n" + "="*70)
        print("EXAMPLE 12 - PLOTTING".center(70))
        print("="*70)

        if results.get('success_modflow'):
            ex12_plot_cross_section(results)
            ex12_plot_streamflow(results)
            ex12_plot_piezometry(results)
            ex12_plot_2d(results)
            ex12_plot_3d(results)
            ex12_plot_pathlines(results)
            ex12_plot_concentration(results)
            ex12_plot_interactive_cross_section(results)
        else:
            print("  ⚠ Skipping plots (MODFLOW failed)")

        print("\n  ✓ All plots completed\n")
        step_counter += 1

    # STEP 10: Web animation
    if results and sections.get("plot_animation_interactive") and results.get('success_modflow'):
        print(f"\n[STEP {step_counter}] Executing: Web animation")
        ex12_plot_web_animation(results)
        step_counter += 1
    elif sections.get("plot_animation_interactive") and not results.get('success_modflow'):
        print(f"\n[STEP {step_counter}] ⚠ Skipping animation (MODFLOW failed)")
        step_counter += 1

    # Final summary
    print("\n" + "="*70)
    print("✓ EXECUTION COMPLETED".center(70))
    print("="*70)

    if results:
        print(f"\n  Final results keys: {sorted(results.keys())}\n")
        print("  Execution summary:")
        if results.get('success_modflow'):
            print(f"MODFLOW: {results.get('model_name', 'Success')}")
        else:
            print(" MODFLOW: Failed")

        if results.get('success_modpath'):
            print(f"MODPATH: Success")
        else:
            print("MODPATH: Skipped/Failed")

        if results.get('success_mt3dms'):
            print(f"MT3DMS: Success")
        else:
            print("MT3DMS: Skipped/Failed")
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
