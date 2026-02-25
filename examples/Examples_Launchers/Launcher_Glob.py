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
from hydromodpy.watershed import Geographic, Initializing, Climatic, Geology, Hydrography, Hydrometry, Intermittency, Settings, Hydraulic, Oceanic, Transport,Subbasin
from hydromodpy.watershed.initializing_config import InitializingConfig
from hydromodpy.watershed.geographic_config import GeographicConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.display import visualization_watershed, visualization_results
from hydromodpy.tools import toolbox
from hydromodpy.calibration_legacy.matching_stream import MatchingStreams as MatchingStreamsCalib

# Import complete workflow functions from modeling_workflow_complete.py
from modeling_workflow_complete import (
    complete_modflow,
    complete_modpath,
    complete_mt3dms,
    complete_timeseries
)


fontprop = toolbox.plot_params(8, 15, 18, 20)

# ============================================================================
# CHOOSE EXAMPLE TO RUN (ex03, ex09, ex12) - MUST BE BEFORE CONFIG LOADING
# ============================================================================
EXAMPLE_TO_RUN = "ex12"  # ← CHANGE THIS TO SWITCH EXAMPLES

# Load configuration from dynamic config file (config03.toml, config09.toml, config12.toml)
config_number = EXAMPLE_TO_RUN[-2:]  # Extract "03", "09", "12"
cfg = HydroModPyConfig.from_toml(Path(__file__).parent / f"config{config_number}.toml")



# ============================================================================
# CONFIG - MULTIPLE EXAMPLES (ex03, ex09, ex12)
# ============================================================================

CONFIG_OPTIONS = {
    "ex04": {
        "example": "ex04",
        "display_figures": False,
        "sections": {
            "watershed": True,
            "data": True,
            "recharge": True,
            "parametrization": True,
            "modeling": True,
            "plot": False,
            "matching_streams": False,
            "modpath": False,
            "mt3dms": False
        },
        "plots": {
            "plot_2d": False,
            "plot_3d": False,
            "web_animation": False
        }
    },
    "ex03": {
        "example": "ex03",
        "display_figures": True,
        "sections": {
            "watershed": True,
            "data": True,
            "recharge": True,
            "parametrization": True,
            "modeling": True,
            "plot": False,
            "plot_cross_section": True,
            "plot_map": True,
            "plot_graph": True,
            "matching_streams": False,
            "modpath": True,
            "mt3dms": False
        },
        "plots": {
            "plot_cross_section": True,
            "plot_map": True,
            "plot_graph": True
        }
    },
    "ex09": {
        "example": "ex09",
        "display_figures": True,
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
            "plot_animation_interactive": False
        },
        "plots": {
            "plot_2d": False,
            "plot_3d": False,
            "web_animation": True
        }
    },
    "ex12": {
        "example": "ex12",
        "display_figures": True,
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
            "plot_animation_interactive": False
        },
        "plots": {
            "recharge_runoff": True,
            "streamflow": True,
            "piezometry": True,
            "cross_section": True,
            "pathlines": True,
            "concentration": True,
            "interactive_cross_section": True,
            "plot_2d": True,
            "plot_3d": True,
            "web_animation": True
        }
    },
    "ex00": {
        "example": "ex00",
        "display_figures": False,
        "sections": {
            "watershed": True,
            "data": True,
            "recharge": True,
            "parametrization": True,
            "modeling": True,
            "plot": False,
            "plot_cross_section": False,
            "plot_map": False,
            "plot_graph": False,
            "modpath": True,
            "mt3dms": False
        },
        "plots": {
            "plot_cross_section": False,
            "plot_map": False,
            "plot_graph": False
        }
    },
    "ex01": {
        "example": "ex01",
        "display_figures": True,
        "sections": {
            "watershed": True,
            "data": True,
            "recharge": True,
            "parametrization": True,
            "modeling": True,
            "plot": False,
            "plot_cross_section": False,
            "plot_map": False,
            "plot_graph": False,
            "modpath": True,
            "mt3dms": False
        },
        "plots": {
            "plot_cross_section": True,
            "plot_map": True,
            "plot_graph": True
        }
    }
}

# ============================================================================
# CONFIG SELECTION (uses EXAMPLE_TO_RUN defined above)
# ============================================================================
CONFIG = CONFIG_OPTIONS[EXAMPLE_TO_RUN]

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
        # Well pumping settings
        "well_1_coords": [0, 39, 39],  # [layer-1, row-1, col-1]
        "well_2_coords": [0, 64, 64],  # [layer-1, row-1, col-1]
        "well_1_fluxes": [-200, -1000, -100, 0, 0, 0, 0, 0, 0, 0, 0, -1000],  # [L3/T] for 12 stress periods
        "well_2_fluxes": [0, -1000, 0, -500, 0, 0, -500, 0, 0, 0, 0, -1000],  # [L3/T] for 12 stress periods
        # Vertical anisotropy exponent
        "exdp": 1.0,
        # Transport (MT3DMS) settings
        "spc_name": "NO3",
        "disp_long": 0,  # Longitudinal dispersivity (m)
        "disp_transh": 0,  # Transverse horizontal dispersivity
        "disp_transv": 0,  # Transverse vertical dispersivity
        "diffu_coeff": 1e-10 * 3600 * 24,  # Molecular diffusion (L2T-1)
        "react_order": 1,  # 0: zero-order, 1: first-order
        "sconc_init_value": 100,  # Initial concentration (mg/L)
        "sconc_input_value": 50,  # Input concentration (mg/L)
        "rate_decay_value": 1 / (2 * 365),  # Decay rate (T-1) - half-life 2 years
        "plot_conc": True,
        # Plotting parameters (ex12 uses monthly data)
        "plot_params": {
            "factor": 30,  # Monthly data
            "n_subplots": 3,  # Include synthetic recharge
            "figsize_recharge": (8, 8),
            "figsize_streamflow": (12, 3.5),
            "figsize_piezometry": (12, 3.5),
            "figsize_cross_section": (6, 4),
            "figsize_pathlines": (8, 6),
        },
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
        # Well pumping settings (optional for ex09)
        "well_1_coords": [],
        "well_2_coords": [],
        "well_1_fluxes": [],
        "well_2_fluxes": [],
        # Vertical anisotropy exponent
        "exdp": 1.0,
        # Transport (MT3DMS) settings
        "spc_name": "NO3",
        "disp_long": 0,  # Longitudinal dispersivity (m)
        "disp_transh": 0,  # Transverse horizontal dispersivity
        "disp_transv": 0,  # Transverse vertical dispersivity
        "diffu_coeff": 1e-10 * 3600 * 24,  # Molecular diffusion (L2T-1)
        "react_order": 1,  # 0: zero-order, 1: first-order
        "sconc_init_value": 100,  # Initial concentration (mg/L)
        "sconc_input_value": 50,  # Input concentration (mg/L)
        "rate_decay_value": 1 / (2 * 365),  # Decay rate (T-1) - half-life 2 years
        "plot_conc": True,
        # Plotting parameters (ex09 uses weekly-like scaling, different subplot layout)
        "plot_params": {
            "factor": 7,  # Weekly-like scaling
            "n_subplots": 2,  # Simplified (no synthetic recharge)
            "figsize_recharge": (8, 5),
            "figsize_streamflow": (12, 3.5),
            "figsize_piezometry": (12, 3.5),
            "figsize_cross_section": (6, 4),
            "figsize_pathlines": (8, 6),
        },
    },
    "ex04": {
        "base_path": "examples/04S_short",
        "dem_filename": "regional dem.tif",
        "dem_coordinates": [391502.195, 6821197.683, 150, 10, 'EPSG:2154'],
        "watershed_name": "04S_short",
        "recharge_first_year": 2000,
        "recharge_last_year": 2001,
        "recharge_time_step": "M",
        # Frame settings
        "box": True,
        "sink_fill": False,
        "sim_state": "transient",
        "dis_perlen": True,
        "plot_cross": False,
        "check_grid": False,
        # Hydraulic parameters
        "nlay": 1,
        "lay_decay": 1,
        "bottom": None,
        "thickness": 30,
        "hk": 5e-5 * 24 * 3600,  # m/day
        "cond_drain": None,
        "bc_left": None,
        "bc_right": None,
        "sea_level": "None",
        # Looping over porosity (Sy)
        "iD_set_simulations": "explorSy_test1",
        "list_porosity": [0.5, 5],  # in percent
        # Plotting parameters
        "plot_params": {
            "factor": 30,
            "n_subplots": 2,
            "figsize_recharge": (6, 3),
            "figsize_streamflow": (10, 3),
            "figsize_piezometry": (12, 3.5),
            "figsize_cross_section": (6, 4),
            "figsize_pathlines": (8, 6),
        }
    },
    "ex03": {
        "base_path": "examples/03S_short",
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
        # Multiple models
        "iD_set_simulations": "explorK_test1",
        "list_hyd_cond": list(np.geomspace(1e-8, 1e-3, 10)),  # in m/s (10 values)
        # Plotting parameters
        "plot_params": {
            "factor": 30,
            "n_subplots": 2,
            "figsize_recharge": (8, 5),
            "figsize_streamflow": (12, 3.5),
            "figsize_piezometry": (12, 3.5),
            "figsize_cross_section": (6, 4),
            "figsize_pathlines": (8, 6),
        }
        },

    "ex00": {
        "base_path": "examples/00S_short",
        "dem_filename": "regional dem.tif",
        "dem_coordinates": [150727.164, 6858066.520, 100, 10, 'EPSG:2154'],
        "watershed_name": "00S_short",
        "recharge_first_year": 2017,
        "recharge_last_year": 2017,
        "recharge_time_step": "D",
        # Frame settings
        "box": True,
        "sink_fill": False,
        "sim_state": "transient",
        "dis_perlen": True,  # Auto-calculated from monthly stress periods
        # Check model
        "plot_cross": True,
        "check_grid": True,
        # Hydraulic parameters
        "verti_hk": None,
        "verti_sy": None,
        "verti_ss": None,
        "sy": 1 / 100,
        "sy_decay": 0,
        "ss": 1e-5,
        "ss_decay": 0,
        "vka": 1,
        "bottom": None,
        "thickness": 50,
        "cond_drain": None,
        "bc_left": None,
        "bc_right": None,
        "sea_level": "None",
        "nlay": 1,
        "lay_decay": 1,
        # Complex K/Sy parameters (for potential use)
        "alpha": 15,
        "n_factor": 2,
        "the_K0": 1e-5,  # in m/s (from example_00.py: 1e-5 m/s = 0.864 m/d)
        "Kmin_for_hk_decay": 1e-8 * 24 * 3600,
        "the_sy0": 2 / 100,
        "Symin_for_sy_decay": 0.1 / 100,
        "the_ss0": 1e-10,
        "Klog_transf": False,
        "vers": "TRANS1",
        # Recharge data
        "recharge_monthly": [10, 60, 40, 20, 10, 5, 4, 20, 10, 1, 0, 0],  # mm/month for 2017
        # Well pumping settings
        "well_1_coords": [0, 8, 28],  # [layer-1, row-1, col-1]
        "well_2_coords": [0, 16, 28],  # [layer-1, row-1, col-1]
        "well_1_fluxes": [-200, 0, -100, 0, 0, 0, 0, 0, 0, 0, 0, 0],  # [L3/T] for 12 stress periods
        "well_2_fluxes": [-500, 0, 0, -500, 0, 0, -500, 0, 0, 0, 0, 0],  # [L3/T] for 12 stress periods
        # Plotting parameters
        "plot_params": {
            "factor": 30,
            "n_subplots": 2,
            "figsize_recharge": (8, 5),
            "figsize_streamflow": (12, 3.5),
            "figsize_piezometry": (12, 3.5),
            "figsize_cross_section": (6, 4),
            "figsize_pathlines": (8, 6),
        }
    },

    "ex01": {
        "base_path": "examples/01S_short",
        "dem_filename": "regional dem.tif",
        "dem_coordinates": [327816.965, 6777886.670, 150, 10.0, 'EPSG:2154'],
        "watershed_name": "01S_short",
        "recharge_first_year": 1990,
        "recharge_last_year": 2019,
        "recharge_time_step": "D",
        # Frame settings
        "box": True,
        "sink_fill": False,
        "sim_state": "steady",
        "dis_perlen": False,
        # Check model
        "plot_cross": False,
        "check_grid": True,
        # Hydraulic parameters
        "verti_hk": None,
        "verti_sy": None,
        "verti_ss": None,
        "sy": 1 / 100,
        "sy_decay": 1 / 20,
        "ss": None,
        "ss_decay": 1 / 20,
        "vka": None,
        "bottom": None,
        "thickness": 50,
        "cond_drain": None,
        "bc_left": None,
        "bc_right": None,
        "sea_level": "None",
        "nlay": 5,
        "lay_decay": 1.5,
        # Conduct HK
        "hk": 2e-5 * 24 * 3600,  # m/d
        "hk_decay": 1 / 20,
        "Kmin_for_hk_decay": None,
        "Klog_transf": False,
        # Complex K/Sy parameters (not used in ex01)
        "alpha": None,
        "n_factor": None,
        "the_K0": None,
        "the_sy0": None,
        "Symin_for_sy_decay": None,
        "the_ss0": None,
        "vers": None,
        # Recharge data
        "recharge": 350 / 1000 / 365,  # Scalar for steady state
        "recharge_monthly": None,
        # Well pumping settings (not used in ex01)
        "well_1_coords": None,
        "well_2_coords": None,
        "well_1_fluxes": None,
        "well_2_fluxes": None,
        # Model identification
        "iD_set_simulations": None,
        "list_hyd_cond": None,
        # Plotting parameters
        "plot_params": {
            "factor": 30,
            "n_subplots": 2,
            "figsize_recharge": (8, 5),
            "figsize_streamflow": (12, 3.5),
            "figsize_piezometry": (12, 3.5),
            "figsize_cross_section": (6, 4),
            "figsize_pathlines": (8, 6),
        }
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
        "subbasin": {
            "class_name": "Subbasin",
            "constructor_args": {
                "geographic": ("geographic", True),
                "hydrometry": (None, False),
                "intermittency": (None, False),
                "add_path": ("data_path", True),
                "out_path": ("initializing.catch_folder", True),
                "sub_snap_dist": (50, False)
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
    },
    "ex09": {
        "hydrography": {
            "class_name": "Hydrography",
            "constructor_args": {
                "out_path": ("initializing.catch_folder", True),
                "types_obs": (["botopage2024_naizin_streams_perennial-intermittent"], False),
                "fields_obs": (["FID"], False),
                "geographic": ("geographic", False),
                "hydro_path": ("data_path", True),
                "streams_file": (None, False)
            }
        },
        "subbasin": {
            "class_name": "Subbasin",
            "constructor_args": {
                "geographic": ("geographic", True),
                "hydrometry": (None, False),
                "intermittency": (None, False),
                "add_path": ("data_path", True),
                "out_path": ("initializing.catch_folder", True),
                "sub_snap_dist": (50, False)
            }
        }
    },
    "ex04": {
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
                "types_obs": (["regional stream network"], False),
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
        },
        "subbasin": {
            "class_name": "Subbasin",
            "constructor_args": {
                "geographic": ("geographic", True),
                "hydrometry": (None, False),
                "intermittency": (None, False),
                "add_path": ("data_path", True),
                "out_path": ("initializing.catch_folder", True),
                "sub_snap_dist": (150, False)
            }
        }
    },
    "ex03": {
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
                "types_obs": (["regional stream network"], False),
                "fields_obs": (["FID"], False),
                "geographic": ("geographic", True),
                "hydro_path": ("data_path", True),
                "streams_file": (None, False)
            }
        },
        "subbasin": {
            "class_name": "Subbasin",
            "constructor_args": {
                "geographic": ("geographic", True),
                "hydrometry": (None, False),
                "intermittency": (None, False),
                "add_path": ("data_path", True),
                "out_path": ("initializing.catch_folder", True),
                "sub_snap_dist": (150, False)
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
    },
    "ex00": {
        "hydrography": {
            "class_name": "Hydrography",
            "constructor_args": {
                "out_path": ("initializing.catch_folder", True),
                "types_obs": (["regional stream network"], False),
                "fields_obs": (["FID"], False),
                "geographic": ("geographic", True),
                "hydro_path": ("data_path", True),
                "streams_file": (None, False)
            }
        }
    },
    "ex01": {
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
                "types_obs": (["regional stream network"], False),
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
        },
        "subbasin": {
            "class_name": "Subbasin",
            "constructor_args": {
                "geographic": ("geographic", True),
                "hydrometry": (None, False),
                "intermittency": (None, False),
                "add_path": ("data_path", True),
                "out_path": ("initializing.catch_folder", True),
                "sub_snap_dist": (150, False)
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
    },
    "ex04": {
        "check_model": {"plot_cross": False, "check_grid": False},
        "climatic": {
            "recharge_from_results": True,
            "runoff_factor": 0.1
        },
        "hydraulic_specific": {
            "update_ss": False,
            "update_vka": False,
            "update_vertical": False,
            "update_decay": False,
            "sy_complex": False
        },
        "particle_tracking": True
    },
    "ex03": {
        "check_model": {"plot_cross": True, "check_grid": True},
        "climatic": {
            "recharge_from_params": True,
            "runoff": None
        },
        "hydraulic_specific": {
            "update_bottom": True,
            "update_thick": True,
            "update_sy_simple": True,
            "decay_config": False
        },
        "particle_tracking": True
    },
    "ex00": {
        "check_model": {"plot_cross": False, "check_grid": False},
        "climatic": {
            "recharge_from_params": True,
            "runoff": None
        },
        "hydraulic_specific": {
            "update_sy_simple": True,
            "decay_config": False
        },
        "particle_tracking": False
    },
    "ex01": {
        "check_model": {"plot_cross": False, "check_grid": True},
        "climatic": {
            "recharge_from_results": True,
            "runoff_factor": None
        },
        "hydraulic_specific": {
            "update_hk": True,
            "update_hk_decay": True,
            "update_sy_simple": True,
            "update_ss": False,
            "update_vka": False,
            "update_hk_vertical": False,
            "update_decay": True,
            "decay_config": True
        },
        "particle_tracking": True
    }
}



# ============================================================================
# MODELING CONFIG - EXAMPLE 12
# ============================================================================

MODELING_CONFIG = {
    "ex12": {
        "type": "single",
        "preprocessing": {"for_calib": False},
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
            "intermittency_weekly": False,
            "intermittency_monthly": True,
            "intermittency_yearly": False,
            "export_all_tif": False
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
    },
    "ex04": {
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
            "accumulation_flux": True,
            "persistency_index": True,
            "intermittency_monthly": True,
            "intermittency_daily": False,
            "export_all_tif": False
        },
        "postprocessing_timeseries": {
            "datetime_format": True,
            "subbasin_results": True
        },
        "postprocessing_netcdf": True,
        "check_model": {
            "plot_cross": False,
            "check_grid": False
        }
    },
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
    "ex00": {
        "type": "single",
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
            "accumulation_flux": True,
            "persistency_index": True,
            "intermittency_monthly": True,
            "intermittency_weekly": False,
            "intermittency_daily": False,
            "export_all_tif": True
        },
        "postprocessing_timeseries": {
            "datetime_format": False,
            "subbasin_results": False
        },
        "postprocessing_netcdf": {
            "datetime_format": False
        },
        "check_model": {
            "plot_cross": True,
            "check_grid": True
        }
    },
    "ex01": {
        "type": "single",
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
            "accumulation_flux": True,
            "persistency_index": False,
            "intermittency_monthly": False,
            "intermittency_weekly": False,
            "intermittency_daily": False,
            "export_all_tif": False
        },
        "postprocessing_timeseries": {
            "datetime_format": False,
            "subbasin_results": True
        },
        "postprocessing_netcdf": {
            "datetime_format": False
        },
        "check_model": {
            "plot_cross": False,
            "check_grid": True
        }
    }
}


# ============================================================================
# MODPATH CONFIG - EXAMPLE 12
# ============================================================================

MODPATH_CONFIG = {
    "ex12": {
        "preprocessing": {
            "zone_partic": "seepage_areas",
            "cell_div": 1,
            "zloc_div": False,
            "bore_depth": None,
            "track_dir": "backward",
            "sel_random": None,
            "sel_slice": None,
        },
        "processing": {
            "write_model": True,
            "run_model": True,
        },
        "post_processing": {
            "ending_point": True,
            "starting_point": True,
            "pathlines_shp": True,
            "particles_shp": True,
            "random_id": None,
        },
        "filt_processing": {
            "norm_flux": True,
            "filt_time": True,
            "filt_seep": True,
            "filt_inout": True,
            "calc_rtd": False,
            "random_id": None,
        }
    },
     "ex09": {
        "preprocessing": {
            "zone_partic": "seepage_areas",
            "cell_div": 1,
            "zloc_div": False,
            "bore_depth": None,
            "track_dir": "backward",
            "sel_random": None, # or int
            "sel_slice": None, # ot int
        },
        "processing": {
            "write_model": True,
            "run_model": True,
        },
        "post_processing": {
            "ending_point": True,
            "starting_point": True,
            "pathlines_shp": True,
            "particles_shp": True,
            "random_id": None,
        },
        "filt_processing": {
            "norm_flux": True,
            "filt_time": True,
            "filt_seep": True,
            "filt_inout": True,
            "calc_rtd": False,
            "random_id": None,
        }
    },
    "ex03": {
        "preprocessing": {
            "zone_partic": "seepage_areas",
            "cell_div": 1,
            "zloc_div": False,
            "bore_depth": None,
            "track_dir": "backward",
            "sel_random": None,
            "sel_slice": None,
        },
        "processing": {
            "write_model": True,
            "run_model": True,
        },
        "post_processing": {
            "ending_point": True,
            "starting_point": True,
            "pathlines_shp": True,
            "particles_shp": True,
            "random_id": None,
        },
        "filt_processing": {
            "norm_flux": True,
            "filt_time": True,
            "filt_seep": True,
            "filt_inout": True,
            "calc_rtd": False,
            "random_id": None,
        }
    },
    "ex00": {
        "preprocessing": {
            "zone_partic": "seepage_areas",
            "cell_div": 1,
            "zloc_div": False,
            "bore_depth": None,
            "track_dir": "backward",
            "sel_random": None,
            "sel_slice": None,
        },
        "processing": {
            "write_model": True,
            "run_model": True,
        },
        "post_processing": {
            "ending_point": True,
            "starting_point": True,
            "pathlines_shp": True,
            "particles_shp": False,
            "random_id": None,
        },
        "filt_processing": {
            "norm_flux": True,
            "filt_time": True,
            "filt_seep": True,
            "filt_inout": True,
            "calc_rtd": True,
            "random_id": None,
        }
    },
    "ex01": {
        "preprocessing": {
            "zone_partic": "seepage_areas",
            "cell_div": 1,
            "zloc_div": False,
            "bore_depth": None,
            "track_dir": "backward",
            "sel_random": None,
            "sel_slice": None,
        },
        "processing": {
            "write_model": True,
            "run_model": True,
        },
        "post_processing": {
            "ending_point": True,
            "starting_point": True,
            "pathlines_shp": True,
            "particles_shp": False,
            "random_id": None,
        },
        "filt_processing": {
            "norm_flux": True,
            "filt_time": True,
            "filt_seep": True,
            "filt_inout": True,
            "calc_rtd": True,
            "random_id": None,
        }
    }
}
# ============================================================================
# MT3DMS CONFIG - EXAMPLE 12
# ============================================================================

MT3DMS_CONFIG = {
    "ex12": {
        "preprocessing": {
            "for_calib": False,
            # Transport parameters (scalar values; arrays are computed at runtime)
            "spc_name": "NO3",
            "disp_long": 0,
            "disp_transh": 0,
            "disp_transv": 0,
            "diffu_coeff": 1e-10 * 3600 * 24,
            "react_order": 1,
            "plot_conc": True,
        },
        "processing": {
            "write_model": True,
            "run_model": True,
            "verbose": True,
        },
        "post_processing": {
            "concentration_seepage": True,
            "mass_seepage": True,
            "mass_accumulated": True,
            "export_all_tif": True,
        },
        "timeseries": {
            "datetime_format": True,
            "subbasin_results": True,
            "intermittency_weekly": False,
            "intermittency_monthly": True,
            "residence_times": True,
            "concentration_seepage": True,
            "mass_accumulated": True,
        }
    },
    "ex09": {
        "preprocessing": {
            "for_calib": False,
            # Transport parameters (scalar values; arrays are computed at runtime)
            "spc_name": "NO3",
            "disp_long": 0,
            "disp_transh": 0,
            "disp_transv": 0,
            "diffu_coeff": 1e-10 * 3600 * 24,
            "react_order": 1,
            "plot_conc": True,
        },
        "processing": {
            "write_model": True,
            "run_model": True,
            "verbose": True,
        },
        "post_processing": {
            "concentration_seepage": True,
            "mass_seepage": True,
            "mass_accumulated": True,
            "export_all_tif": True,
        },
        "timeseries": {
            "datetime_format": True,
            "subbasin_results": True,
            "intermittency_weekly": False,
            "intermittency_monthly": True,
            "residence_times": True,
            "concentration_seepage": True,
            "mass_accumulated": True,
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



def watershed(example_key):
    """Extract watershed for example 12 (loads config from config.toml)"""
    print("\n" + "="*70)
    print("EXAMPLE 12 - WATERSHED EXTRACTION".center(70))
    print("="*70)

    try:
        # Load paths from PARAMS (for data directory reference)
        #example_key = results.get('example_key', CONFIG["example"])
        p = PARAMS[example_key]
        example_path = os.path.join(root_dir, p["base_path"])
        data_path = os.path.join(example_path, "data")

        if not os.path.exists(data_path):
            print(f"Data path not found: {data_path}\n")
            return None

        print(f"\n Configuration loaded from: config.toml")
        print(f" Data path: {data_path}")

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

        # Visualizations (using available DATA_MODULES configuration)
        viz_list = []  # Placeholder for future visualization enhancements using DATA_MODULES
        if viz_list:
            print("\n Creating watershed visualizations...")
            for viz in viz_list:
                try:
                    method_name = viz["method"]
                    if hasattr(visualization_watershed, method_name):
                        print(f" {viz['name']}...", end="", flush=True)

                        if viz.get("dem_param"):
                            # watershed_local requires dem_init_path as first parameter
                            dem_filename = PARAMS[example_key].get("dem_filename", "watershed_dem.tif")
                            if dem_filename:
                                dem_path = os.path.join(data_path, dem_filename)
                                if os.path.exists(dem_path):
                                    getattr(visualization_watershed, method_name)(dem_path, results.get('initializing'), results.get('geographic'))
                                    print(" True")
                                else:
                                    print(f"DEM not found: {dem_path}")
                        elif viz.get("extended"):
                            # watershed_dem requires initializing, geographic, hydrography, piezometry, intermittency, hydrometry
                            getattr(visualization_watershed, method_name)(
                                initializing=results.get('initializing'),
                                geographic=results.get('geographic'),
                                hydrography=results.get('hydrography'),
                                piezometry=None,
                                intermittency=results.get('intermittency'),
                                hydrometry=results.get('hydrometry')
                            )
                            print(" True")
                        else:
                            # Simple method call with geographic only
                            getattr(visualization_watershed, method_name)(results.get('geographic'))
                            print(" True")
                except Exception as e:
                    print(f"Error: {e}")

        print("Data integration completed\n")
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
            print(" Creating Climatic object...")
            initializing_object = results['initializing']
            climatic_object = Climatic(out_path=initializing_object.catch_folder)
            results['climatic'] = climatic_object

        # FOR EX00: Create recharge manually from monthly data (like example_00.py)
        if example_key == "ex00":
            print("Creating recharge series from monthly data (ex00)...")
            time_index = pd.date_range(start='2017-01-01', end='2017-12-31', freq='ME')
            rch_series = pd.Series(p.get("recharge_monthly", [0]*12)) / 1000 / 30  # mm/month to m/day
            recharge = pd.Series(rch_series.values, index=time_index)
            climatic_object.update_recharge(recharge, sim_state=p["sim_state"])
            climatic_object.update_runoff(None, sim_state=p["sim_state"])
            climatic_object.update_first_clim('mean')

            results['R_mm_day'] = climatic_object.recharge
            results['runoff'] = climatic_object.runoff
            results['climatic'] = climatic_object
            print("Recharge and runoff created\n")
            return results

        # FOR OTHER EXAMPLES: Read from REANALYSIS file
        print("Update recharge (REANALYSIS)...")
        climatic_object.update_recharge_reanalysis(
            path_file=os.path.join(data_path, '_climate_REANALYSIS.csv'),
            clim_mod='REA',
            clim_sce='historic',
            first_year=p["recharge_first_year"],
            last_year=p["recharge_last_year"],
            time_step=p["recharge_time_step"],
            sim_state=p["sim_state"]
        )

        print("Update runoff (REANALYSIS)...")
        climatic_object.update_runoff_reanalysis(
            path_file=os.path.join(data_path, '_climate_REANALYSIS.csv'),
            clim_mod='REA',
            clim_sce='historic',
            first_year=p["recharge_first_year"],
            last_year=p["recharge_last_year"],
            time_step=p["recharge_time_step"],
            sim_state=p["sim_state"]
        )

        print("Recharge and runoff loaded\n")

        results['R_mm_day'] = climatic_object.recharge
        results['runoff'] = climatic_object.runoff
        results['climatic'] = climatic_object

        return results

    except Exception as e:
        print(f"Error: {e}\n")
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

        print("Configuring individual objects...")

        # Configure Settings (like example12.py)
        print("Settings...")
        settings_object.update_box_model(p["box"])
        settings_object.update_sink_fill(p["sink_fill"])
        settings_object.update_simulation_state(p["sim_state"])
        settings_object.update_bc_sides(p["bc_left"], p["bc_right"])
        settings_object.update_dis_perlen(dis_perlen=p["dis_perlen"])

        # Configure well pumping (optional)
        well_1_coords = p.get("well_1_coords", [])
        well_2_coords = p.get("well_2_coords", [])
        well_1_fluxes = p.get("well_1_fluxes", [])
        well_2_fluxes = p.get("well_2_fluxes", [])

        if well_1_coords or well_2_coords:
            settings_object.update_well_pumping(
                well_coords=[well_1_coords, well_2_coords],
                well_fluxes=[pd.Series(well_1_fluxes) if well_1_fluxes else pd.Series([]),
                            pd.Series(well_2_fluxes) if well_2_fluxes else pd.Series([])]
            )
        else:
            settings_object.update_well_pumping(well_coords=[], well_fluxes=[])

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
        hydraulic_object.update_exdp(p.get("exdp", 1.0))

        # Configure Transport (created for all, configured as needed)
        print("    • Transport...")
        transport_object = results.get('transport')
        if transport_object is None:
            transport_object = Transport()
            results['transport'] = transport_object

        transport_object.update_mt3dms_parameters(
            spc_name=p.get("spc_name"),
            sconc_init=None,  # Will be set in MT3DMS based on model dimensions
            sconc_input=None,  # Will be set in MT3DMS based on model dimensions
            disp_long=p.get("disp_long"),
            disp_transh=p.get("disp_transh"),
            disp_transv=p.get("disp_transv"),
            diffu_coeff=p.get("diffu_coeff"),
            react_order=p.get("react_order"),
            rate_decay=None,  # Will be set in MT3DMS based on model dimensions
            plot_conc=p.get("plot_conc")
        )
        # Store transport parameters as scalars for later use by mt3dms_ex12
        transport_object.sconc_init_value = p.get("sconc_init_value", 0) / 1000  # Convert mg/L to kg/m3
        transport_object.sconc_input_value = p.get("sconc_input_value", 0) / 1000
        transport_object.rate_decay_value = p.get("rate_decay_value", 0)

        # Configure Climatic (like example12.py)
        print("    • Climatic...")
        climatic_object.update_first_clim('mean')

        # Handle recharge based on example type
        if example_key == "ex00":
            # ex00: recharge already created in recharge() function, skip here
            pass

        elif config["climatic"].get("recharge_from_results"):
            R_mm_day = results.get('R_mm_day')
            if R_mm_day is not None:
                # Handle both pandas Series (ex00, ex09, ex12) and scalar (ex01)
                if isinstance(R_mm_day, pd.Series):
                    recharge = R_mm_day / 1000
                else:  # scalar value
                    recharge = R_mm_day / 1000
            else:
                recharge = pd.Series([0.1] * 365) / 1000
            climatic_object.update_recharge(recharge, sim_state=p["sim_state"])

            if config["climatic"].get("runoff_factor"):
                runoff = recharge * config["climatic"]["runoff_factor"]
                climatic_object.update_runoff(runoff, sim_state=p["sim_state"])

        elif config["climatic"].get("recharge_from_params"):
            # ex03: use monthly recharge values from PARAMS
            recharge_monthly = p.get("recharge_monthly", [0]*12)
            climatic_object.update_recharge(recharge_monthly, sim_state=p["sim_state"])

        # HYDRAULIC SPECIFIC
        print("  • Update hydraulic specific...")

        if config["hydraulic_specific"].get("update_hk"):
            hydraulic_object.update_hk(p["hk"])

        if config["hydraulic_specific"].get("update_sy_simple"):
            hydraulic_object.update_sy(p["sy"])

        if config["hydraulic_specific"].get("update_ss"):
            hydraulic_object.update_ss(p["ss"])

        if config["hydraulic_specific"].get("update_vka"):
            hydraulic_object.update_vka(p["vka"])

        if config["hydraulic_specific"].get("update_hk_vertical"):
            hydraulic_object.update_hk_vertical(p["verti_hk"])

        if config["hydraulic_specific"].get("update_decay"):
            if config["hydraulic_specific"].get("update_hk_decay"):
                hydraulic_object.update_hk_decay(p["hk_decay"], min_value=p.get("Kmin_for_hk_decay"), log_transf=p.get("Klog_transf"))
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
            the_K0 = p.get("the_K0")
            if the_K0 is not None:
                the_K0_ms = the_K0 / 24 / 3600
                model_name = f"{p['vers']}_K{the_K0_ms:.1e}_a{p['alpha']:.1f}_Sy{p['the_sy0']*100:.1f}"
            else:
                # ex01: use hk from PARAMS, no version/alpha naming
                model_name = f"{example_key}_hk{p['hk']:.1e}"

            # Call refactored complete_modflow function with individual objects
            hk_value = p.get("the_K0") if p.get("the_K0") is not None else p.get("hk")
            result = complete_modflow(
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

            results['model_name'] = result['model_name']
            results['model_modflow'] = result['model_modflow']
            results['success_modflow'] = result['success']

            print("MODFLOW model created\n")
            return results

        # For multiple models (example 03 uses "multiple" type OR example 04 loops over Sy)
        else:
            base_name = p["iD_set_simulations"]
            list_model_name = []
            list_success_modflow = []
            list_model_modflow = []

            # Check if this is ex03 (loops over HK) or ex04 (loops over Sy/porosity)
            if example_key == "ex03" and p.get("list_hyd_cond"):
                # EX03: Loop over hydraulic conductivity
                hk_values = [h * 24 * 3600 for h in p["list_hyd_cond"]]
                model_names = [f"{base_name}_{round(h, 3)}" for h in hk_values]

                for i, (hk_value, model_name) in enumerate(zip(hk_values, model_names)):
                    print(f"    Model {i+1}/{len(hk_values)}: {model_name}")

                    result = complete_modflow(
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

            elif example_key == "ex04" and p.get("list_porosity"):
                # EX04: Loop over porosity (Sy)
                sy_values = [s / 100 for s in p["list_porosity"]]  # Convert percent to fraction
                hk_fixed = p["hk"]  # Fixed HK value for ex04

                for i, sy_value in enumerate(sy_values):
                    model_name = f"{base_name}_{i}_{round(sy_value, 3)}"
                    print(f"    Model {i+1}/{len(sy_values)}: {model_name}")

                    # Update Sy for this iteration (like example_04.py line 275)
                    hydraulic_object.update_sy(sy_value)
                    settings_object.update_model_name(model_name)

                    result = complete_modflow(
                        geographic=geographic_object,
                        hydraulic=hydraulic_object,
                        settings=settings_object,
                        climatic=climatic_object,
                        oceanic=oceanic_object,
                        initializing=initializing_object,
                        model_name=model_name,
                        hk_value=hk_fixed,  # Use fixed HK for ex04
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

def modpath_ex12(results):
    """SPECIALIZED MODPATH for Example 12 - calls generic modpath() with MODPATH_CONFIG"""
    print("\n  • Executing MODPATH for Example 12...")

    # Initialize success_modpath to False
    results['success_modpath'] = False
    results['model_modpath'] = None

    try:
        # Get individual objects
        geographic_object = results['geographic']
        settings_object = results['settings']
        model_modflow = results['model_modflow']
        initializing_object = results['initializing']
        model_name = results['model_name']

        # CRITICAL: Ensure seepage_areas raster exists before MODPATH
        # (it should have been created by MODFLOW postprocessing, but verify)
        simulations_folder = results['simulations_folder']
        raster_folder = os.path.join(simulations_folder, model_name, '_postprocess/_rasters')
        seepage_tif = os.path.join(raster_folder, 'seepage_areas_t(0).tif')

        if not os.path.exists(seepage_tif):
            print("    WARNING: seepage_areas_t(0).tif missing - regenerating from MODFLOW...")
            try:
                # Call MODFLOW postprocessing specifically to generate seepage_areas rasters
                if model_modflow:
                    print("    Re-running MODFLOW.post_processing()...")
                    postproc_config = MODELING_CONFIG['ex12'].get('postprocessing_modflow', {})
                    model_modflow.post_processing(model_modflow, **postproc_config)

                    if os.path.exists(seepage_tif):
                        print(f"    ✓ seepage_areas_t(0).tif regenerated successfully")
                    else:
                        print(f"    ⚠ seepage_areas_t(0).tif still not found after postprocessing")
            except Exception as e:
                print(f"    ⚠ Could not regenerate seepage_areas: {e}")

        # Use MODPATH_CONFIG with all parameter subsections
        config = MODPATH_CONFIG.get('ex12', {})

        # Call refactored complete_modpath with config
        # for_calib=False because we're in simulations mode (not calibration)
        modpath_result = complete_modpath(
            geographic=geographic_object,
            settings=settings_object,
            model_modflow=model_modflow,
            initializing=initializing_object,
            model_name=model_name,
            for_calib=False,
            config=config
        )

        results['model_modpath'] = modpath_result.get('model_modpath')
        results['success_modpath'] = modpath_result.get('success', False)

        if results['success_modpath']:
            print("  ✓ MODPATH completed\n")
        else:
            print("  ⚠ MODPATH returned success=False\n")

        return results
    except Exception as e:
        print(f"    ✗ MODPATH error: {e}")
        import traceback
        traceback.print_exc()
        results['success_modpath'] = False
        results['model_modpath'] = None
        return results


def mt3dms_ex12(results):
    """SPECIALIZED MT3DMS for Example 12 - uses transport_object configuration"""
    print("\n  • Executing MT3DMS for Example 12...")
    try:
        # Get individual objects
        geographic_object = results['geographic']
        model_modflow = results['model_modflow']
        initializing_object = results['initializing']
        model_name = results['model_name']
        transport_object = results.get('transport')

        if not model_modflow or not results.get('success_modflow'):
            print("  ⚠ MODFLOW incomplete - skipping MT3DMS")
            results['success_mt3dms'] = False
            return results

        if not transport_object:
            print("  ⚠ Transport object not configured - skipping MT3DMS")
            results['success_mt3dms'] = False
            return results

        # Setup concentration arrays based on model dimensions (like example12.py)
        nper = model_modflow.nper
        nlay = model_modflow.mf.nlay
        nrow = model_modflow.mf.nrow
        ncol = model_modflow.mf.ncol

        sconc_init = np.ones((nlay, nrow, ncol)) * transport_object.sconc_init_value
        sconc_input = {i: np.ones((nrow, ncol)) * transport_object.sconc_input_value for i in range(nper)}
        sconc_input = dict(islice(sconc_input.items(), 1, None))  # Skip first period
        rate_decay = np.ones((nlay, nrow, ncol)) * transport_object.rate_decay_value

        # Update transport object with arrays
        transport_object.sconc_init = sconc_init
        transport_object.sconc_input = sconc_input
        transport_object.rate_decay = rate_decay

        scenario = 's1'

        # Use MT3DMS_CONFIG with all parameter subsections (dynamic based on example)
        example_key = CONFIG.get("example", "ex12")
        config = MT3DMS_CONFIG.get(example_key, {})

        # Call refactored complete_mt3dms with config
        mt3dms_result = complete_mt3dms(
            geographic=geographic_object,
            climatic=None,
            model_modflow=model_modflow,
            initializing=initializing_object,
            model_name=model_name,
            scenario=scenario,
            for_calib=False,
            transport=transport_object,
            config=config
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
# STEP 6: POSTPROCESSING - TIMESERIES (MODFLOW ONLY)
# ============================================================================

def ex12_postprocessing_timeseries_modflow(results):
    """Generate timeseries results after MODFLOW (before MODPATH/MT3DMS) - Example 12 line 406"""
    print("\n  • Generating timeseries results (MODFLOW only)...")
    try:
        geographic_object = results.get('geographic')
        model_modflow = results.get('model_modflow')

        if not model_modflow:
            print("    ⚠ MODFLOW model not found - skipping timeseries\n")
            results['success_timeseries_modflow'] = False
            return results

        # Call complete_timeseries from modeling_workflow (model_modpath=None, model_mt3dms=None)
        # scenario=None for MODFLOW-only → creates _simulated_timeseries.csv (without suffix)
        ts_result = complete_timeseries(
            geographic=geographic_object,
            model_modflow=model_modflow,
            model_modpath=None,
            model_mt3dms=None,
            scenario=None,
            config=None
        )

        results['timeseries_results_modflow'] = ts_result.get('timeseries_results')
        results['success_timeseries_modflow'] = ts_result.get('success', False)

        if results['success_timeseries_modflow']:
            print("  ✓ Timeseries (MODFLOW only) completed successfully\n")
        else:
            print("  ✗ Timeseries (MODFLOW only) failed\n")

        return results
    except Exception as e:
        print(f"    ✗ Timeseries (MODFLOW only) error: {e}\n")
        import traceback
        traceback.print_exc()
        results['success_timeseries_modflow'] = False
        return results


# STEP 8.5: POSTPROCESSING - TIMESERIES (WITH ALL MODELS)
# ============================================================================

def ex12_postprocessing_timeseries_complete(results):
    """Generate timeseries results after MT3DMS (with all models) - Example 12 line 837"""
    print("\n  • Generating timeseries results (complete with MODPATH + MT3DMS)...")
    try:
        geographic_object = results.get('geographic')
        model_modflow = results.get('model_modflow')
        model_modpath = results.get('model_modpath')
        model_mt3dms = results.get('model_mt3dms')
        scenario = results.get('scenario', 's1')

        if not model_modflow:
            print("    ⚠ MODFLOW model not found - skipping timeseries\n")
            results['success_timeseries_complete'] = False
            return results

        # Call complete_timeseries from modeling_workflow (with all models)
        ts_result = complete_timeseries(
            geographic=geographic_object,
            model_modflow=model_modflow,
            model_modpath=model_modpath,
            model_mt3dms=model_mt3dms,
            scenario=scenario,
            config=None
        )

        results['timeseries_results_complete'] = ts_result.get('timeseries_results')
        results['success_timeseries_complete'] = ts_result.get('success', False)

        if results['success_timeseries_complete']:
            print(" Timeseries (complete) completed successfully\n")
        else:
            print("Timeseries (complete) failed\n")

        return results
    except Exception as e:
        print(f"Timeseries (complete) error: {e}\n")
        import traceback
        traceback.print_exc()
        results['success_timeseries_complete'] = False
        return results


# ============================================================================
# STEP 9.7: PREPARE CONCENTRATION DATA FOR PLOTTING
# ============================================================================

def ex12_prepare_concentration_data(results):
    """Load UCN file and prepare concentration data for plotting (like example12.py)"""
    print("\n  • Preparing concentration data...")
    try:
        model_modflow = results.get('model_modflow')
        model_mt3dms = results.get('model_mt3dms')
        stable_folder = results.get('stable_folder')

        if not model_mt3dms or not results.get('success_mt3dms'):
            print("  ⚠ MT3DMS not available - skipping concentration data preparation")
            results['concobj_1c_fil_surf'] = None
            return results

        if not model_modflow:
            print("  ⚠ MODFLOW model not available")
            results['concobj_1c_fil_surf'] = None
            return results

        # Load UCN file from MT3DMS output (like example12.py line 857)
        ucnobj = bf.UcnFile(model_modflow.full_path + '/' + model_mt3dms.model_name_mt + '.UCN')
        concobj_1c = ucnobj.get_alldata(mflay=None)  # 4D array: [time, lay, row, col]

        # Filter concentration data (like example12.py line 862)
        concobj_1c_fil = concobj_1c.copy() * 1000
        concobj_1c_fil[concobj_1c_fil >= 1e30] = np.nan
        concobj_1c_fil = concobj_1c_fil[:]

        # Build surface concentration array with seepage masking (like example12.py line 874-893)
        concobj_1c_fil_surf = {}
        the_mins = []
        the_maxs = []

        for i in range((model_mt3dms.model_modflow.nper)):
            the_time = i
            # Load seepage data for masking
            seep = imageio.imread(
                os.path.join(model_modflow.full_path,
                           f'_postprocess/_rasters/outflow_drain_t({int(the_time)}).tif')
            )
            # Extract surface layer and mask by seepage
            concobj_1c_fil_surf[the_time] = concobj_1c_fil[the_time + 1][0]
            concobj_1c_fil_surf[the_time] = np.ma.masked_where(seep <= 0, concobj_1c_fil_surf[the_time])

            the_mins.append(np.nanmin(concobj_1c_fil_surf[the_time]))
            the_maxs.append(np.nanmax(concobj_1c_fil_surf[the_time]))

        # Convert to list form for plotting (like example12.py line 898)
        concobj_1c_fil_surf = dict(list(concobj_1c_fil_surf.items())[:])

        # Store in results
        results['concobj_1c_fil_surf'] = concobj_1c_fil_surf
        print(f"  ✓ Concentration data prepared ({len(concobj_1c_fil_surf)} time steps)")

        return results
    except FileNotFoundError as e:
        print(f"  ⚠ Concentration data error - file not found: {e}")
        results['concobj_1c_fil_surf'] = None
        return results
    except Exception as e:
        print(f"  ⚠ Concentration data error: {e}")
        import traceback
        traceback.print_exc()
        results['concobj_1c_fil_surf'] = None
        return results


# ============================================================================
# STEP 7: PLOTTING & ADVANCED ANALYSIS
# ============================================================================


# ============================================================================
# EXEMPLE 09 - MATCHING STREAMS CLASS
# ============================================================================
def ex12_matching_streams(results):
    """MatchingStreams calibration analysis - uses calibration_legacy module"""
    print("  Executing MatchingStreams analysis...")
    if not results:
        return None

    try:
        model_name = results.get('model_name')
        geographic = results.get('geographic')
        hydrography = results.get('hydrography')
        initializing = results.get('initializing')

        if geographic is None or model_name is None or hydrography is None or initializing is None:
            print("Missing required objects (geographic, hydrography, initializing, or model_name)\n")
            return results

        # Instantiate MatchingStreams from calibration_legacy module
        iteration_label = model_name
        print(f"    • Creating MatchingStreams instance with iteration_label: {iteration_label}")

        matching_streams_obj = MatchingStreamsCalib(
            geographic=geographic,
            hydrography=hydrography,
            initializing=initializing,
            iteration_label=iteration_label,
            from_calib=False
        )

        # Store the object and mark as successful
        results['matching_streams'] = matching_streams_obj
        results['success_matching_streams'] = True
        print("    • MatchingStreams methods executed (prepare_files, sim_to_obs, obs_to_sim)")
        print(f"    • Results stored in: {matching_streams_obj.dichotomy_folder}")
        print("MatchingStreams analysis completed\n")

        return results
    except Exception as e:
        print(f"Error in MatchingStreams: {e}\n")
        import traceback
        traceback.print_exc()
        results['success_matching_streams'] = False
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
            "provides": [ "stable_folder", "simulations_folder", "data_path"]
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
            "requires": [ "data_path"],
            "provides": ["climatic", "recharge_data", "runoff_data"]
        },
        {
            "step": 4,
            "section": "parametrization",
            "function": "parametrization()",
            "requires": [ "climatic"],
            "provides": ["settings", "hydraulic_params"]
        },
        {
            "step": 5,
            "section": "modeling",
            "function": "modeling()",
            "requires": [ "settings", "hydraulic_params"],
            "provides": ["model_name", "success_modflow", "model_modflow"]
        },
        {
            "step": 6,
            "section": "matching_streams",
            "function": "ex12_matching_streams()",
            "requires": ["model_name", "model_modflow"],
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
            "requires": ["model_modflow", "success_modflow"],
            "provides": ["model_mt3dms", "success_mt3dms"]
        },
        {
            "step": 9,
            "section": "plot",
            "function": "plot.py functions: plot_recharge_runoff, plot_streamflow, plot_piezometry, plot_cross_section, plot_pathlines, plot_concentration",
            "requires": ["model_name", "success_modflow"],
            "provides": ["visualizations"]
        },
        {
            "step": 10,
            "section": "plot_animation_interactive",
            "function": "ex12_plot_web_animation()",
            "requires": ["model_name", "simulations_folder", "model_modflow"],
            "provides": ["interactive_web_animation"]
        }
    ],
      "ex09": [
        {
            "step": 1,
            "section": "watershed",
            "function": "watershed()",
            "requires": [],
            "provides": [ "stable_folder", "simulations_folder", "data_path"]
        },
        {
            "step": 2,
            "section": "data",
            "function": "data()",
            "requires": [],
            "provides": list(DATA_MODULES["ex09"].keys())
        },
        {
            "step": 3,
            "section": "recharge",
            "function": "recharge()",
            "requires": [ "data_path"],
            "provides": ["climatic", "recharge_data", "runoff_data"]
        },
        {
            "step": 4,
            "section": "parametrization",
            "function": "parametrization()",
            "requires": [ "climatic"],
            "provides": ["settings", "hydraulic_params"]
        },
        {
            "step": 5,
            "section": "modeling",
            "function": "modeling()",
            "requires": [ "settings", "hydraulic_params"],
            "provides": ["model_name", "success_modflow", "model_modflow"]
        },
        {
            "step": 6,
            "section": "matching_streams",
            "function": "ex12_matching_streams()",
            "requires": ["model_name", "model_modflow"],
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
            "requires": ["model_modflow", "success_modflow"],
            "provides": ["model_mt3dms", "success_mt3dms"]
        },
        {
            "step": 9,
            "section": "plot",
            "function": "plot.py functions: plot_recharge_runoff, plot_streamflow, plot_piezometry, plot_cross_section, plot_pathlines, plot_concentration",
            "requires": ["model_name", "success_modflow"],
            "provides": ["visualizations"]
        },
        {
            "step": 10,
            "section": "plot_animation_interactive",
            "function": "ex12_plot_web_animation()",
            "requires": ["model_name", "simulations_folder", "model_modflow"],
            "provides": ["interactive_web_animation"]
        }
    ],
    "ex03": [
        {
            "step": 1,
            "section": "watershed",
            "function": "watershed()",
            "requires": [],
            "provides": ["stable_folder", "simulations_folder", "data_path"]
        },
        {
            "step": 2,
            "section": "data",
            "function": "data()",
            "requires": [],
            "provides": list(DATA_MODULES["ex03"].keys())
        },
        {
            "step": 3,
            "section": "recharge",
            "function": "recharge()",
            "requires": ["data_path"],
            "provides": ["climatic", "recharge_data", "runoff_data"]
        },
        {
            "step": 4,
            "section": "parametrization",
            "function": "parametrization()",
            "requires": ["climatic"],
            "provides": ["settings", "hydraulic_params"]
        },
        {
            "step": 5,
            "section": "modeling",
            "function": "modeling()",
            "requires": ["settings", "hydraulic_params"],
            "provides": ["model_name", "success_modflow", "list_model_modflow"]
        },
        {
            "step": 6,
            "section": "modpath",
            "function": "modpath_ex12()",
            "requires": ["model_modflow", "success_modflow"],
            "provides": ["model_modpath", "success_modpath"]
        },
        {
            "step": 7,
            "section": "plot_cross_section",
            "function": "plot_cross_section_ex03()",
            "requires": ["geographic", "list_model_modflow"],
            "provides": ["cross_section_plots"]
        },
        {
            "step": 8,
            "section": "plot_map",
            "function": "plot_map_ex03()",
            "requires": ["geographic", "list_model_modflow"],
            "provides": ["map_plots"]
        },
        {
            "step": 9,
            "section": "plot_graph",
            "function": "plot_graph_ex03()",
            "requires": ["list_model_modflow"],
            "provides": ["graph_plots"]
        }
    ],
    "ex04": [
        {
            "step": 1,
            "section": "watershed",
            "function": "watershed()",
            "requires": [],
            "provides": ["stable_folder", "simulations_folder", "data_path"]
        },
        {
            "step": 2,
            "section": "data",
            "function": "data()",
            "requires": [],
            "provides": list(DATA_MODULES["ex04"].keys())
        },
        {
            "step": 3,
            "section": "recharge",
            "function": "recharge()",
            "requires": ["data_path"],
            "provides": ["climatic", "recharge_data", "runoff_data"]
        },
        {
            "step": 4,
            "section": "parametrization",
            "function": "parametrization()",
            "requires": ["climatic"],
            "provides": ["settings", "hydraulic_params"]
        },
        {
            "step": 5,
            "section": "modeling",
            "function": "modeling()",
            "requires": ["settings", "hydraulic_params"],
            "provides": ["model_name", "success_modflow", "list_model_modflow"]
        },
        {
            "step": 6,
            "section": "plot",
            "function": "plot_streamflow_saturation_ex04()",
            "requires": ["list_model_modflow"],
            "provides": ["plots"]
        }
    ],
    "ex00": [
        {
            "step": 1,
            "section": "watershed",
            "function": "watershed()",
            "requires": [],
            "provides": ["stable_folder", "simulations_folder", "data_path"]
        },
        {
            "step": 2,
            "section": "data",
            "function": "data()",
            "requires": [],
            "provides": list(DATA_MODULES["ex00"].keys())
        },
        {
            "step": 3,
            "section": "recharge",
            "function": "recharge()",
            "requires": ["data_path"],
            "provides": ["climatic", "recharge_data", "runoff_data"]
        },
        {
            "step": 4,
            "section": "parametrization",
            "function": "parametrization()",
            "requires": ["climatic"],
            "provides": ["settings", "hydraulic_params"]
        },
        {
            "step": 5,
            "section": "modeling",
            "function": "modeling()",
            "requires": ["settings", "hydraulic_params"],
            "provides": ["model_name", "success_modflow", "model_modflow"]
        },
        {
            "step": 6,
            "section": "modpath",
            "function": "modpath_ex12()",
            "requires": ["model_modflow", "success_modflow"],
            "provides": ["model_modpath", "success_modpath"]
        },
        {
            "step": 7,
            "section": "plot_cross_section",
            "function": "plot_cross_section_ex03()",
            "requires": ["geographic", "model_modflow"],
            "provides": ["cross_section_plots"]
        },
        {
            "step": 8,
            "section": "plot_map",
            "function": "plot_map_ex03()",
            "requires": ["geographic", "model_modflow"],
            "provides": ["map_plots"]
        },
        {
            "step": 9,
            "section": "plot_graph",
            "function": "plot_graph_ex03()",
            "requires": ["model_modflow"],
            "provides": ["graph_plots"]
        }
    ],
    "ex01": [
        {
            "step": 1,
            "section": "watershed",
            "function": "watershed()",
            "requires": [],
            "provides": ["stable_folder", "simulations_folder", "data_path"]
        },
        {
            "step": 2,
            "section": "data",
            "function": "data()",
            "requires": [],
            "provides": list(DATA_MODULES["ex01"].keys())
        },
        {
            "step": 3,
            "section": "recharge",
            "function": "recharge()",
            "requires": ["data_path"],
            "provides": ["climatic", "recharge_data", "runoff_data"]
        },
        {
            "step": 4,
            "section": "parametrization",
            "function": "parametrization()",
            "requires": ["climatic"],
            "provides": ["settings", "hydraulic_params"]
        },
        {
            "step": 5,
            "section": "modeling",
            "function": "modeling()",
            "requires": ["settings", "hydraulic_params"],
            "provides": ["model_name", "success_modflow", "model_modflow"]
        },
        {
            "step": 6,
            "section": "modpath",
            "function": "modpath_ex12()",
            "requires": ["model_modflow", "success_modflow"],
            "provides": ["model_modpath", "success_modpath"]
        },
        {
            "step": 7,
            "section": "plot_cross_section",
            "function": "plot_cross_section_ex03()",
            "requires": ["geographic", "model_modflow"],
            "provides": ["cross_section_plots"]
        },
        {
            "step": 8,
            "section": "plot_map",
            "function": "plot_map_ex03()",
            "requires": ["geographic", "model_modflow"],
            "provides": ["map_plots"]
        },
        {
            "step": 9,
            "section": "plot_graph",
            "function": "plot_graph_ex03()",
            "requires": ["model_modflow"],
            "provides": ["graph_plots"]
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
# FUNCTION MAPPING FOR WORKFLOW
# ============================================================================
# Maps workflow section names to their corresponding functions
# Import plot_ex03 functions
from plot_ex03 import plot_cross_section_ex03, plot_map_ex03, plot_graph_ex03

FUNCTION_MAPPING = {
    "watershed": watershed,
    "data": data,
    "recharge": recharge,
    "parametrization": parametrization,
    "modeling": modeling,
    "matching_streams": ex12_matching_streams,
    "modpath": modpath_ex12,
    "mt3dms": mt3dms_ex12,
    "plot_cross_section": plot_cross_section_ex03,
    "plot_map": plot_map_ex03,
    "plot_graph": plot_graph_ex03,
}

# ============================================================================
# MAIN
# ============================================================================


def main():
    """Main execution orchestrator using WORKFLOW_DEFINITION"""
    config = CONFIG
    example_key = config["example"]
    sections = config.get("sections", {})
    workflow = WORKFLOW_DEFINITION.get(example_key, [])

    print("\n" + "="*70)
    print(f"HYDROMODPY - EXAMPLE {example_key.upper()} LAUNCHER".center(70))
    print("="*70)
    print(f"\nEnabled sections: {[s for s, v in sections.items() if v]}\n")

    results = {'success_modflow': False, 'success_modpath': False, 'success_mt3dms': False}
    step_counter = 1

    # Execute workflow steps defined in WORKFLOW_DEFINITION
    for step in workflow:
        section = step["section"]
        function_name = step["function"]

        # Check if section is enabled in CONFIG
        if not sections.get(section):
            continue

        # Check dependencies
        if section in ["matching_streams", "modpath", "mt3dms"] and not results.get('success_modflow'):
            print(f"\n[STEP {step_counter}] ⚠ Skipping {section} (MODFLOW failed)")
            step_counter += 1
            continue

        print(f"\n[STEP {step_counter}] Executing: {function_name}")

        # Get function from mapping
        func = FUNCTION_MAPPING.get(section)
        if func is None:
            print(f"  ✗ Function not found for section {section}")
            step_counter += 1
            continue

        # Watershed is special - takes example_key, others take results
        if section == "watershed":
            results_temp = func(example_key)
            if results_temp:
                results.update(results_temp)
            else:
                print("✗ Watershed extraction failed. Stopping.")
                return None
        else:
            if results:
                results = func(results)

        step_counter += 1

    # Additional processing steps (not in WORKFLOW_DEFINITION)
    # STEP: PREPARE CONCENTRATION DATA (for plotting)
    if results and results.get('success_mt3dms'):
        print(f"\n[STEP {step_counter}] Executing: ex12_prepare_concentration_data()")
        results = ex12_prepare_concentration_data(results)
        step_counter += 1

    # STEP: TIMESERIES - MODFLOW ONLY (first generation: MODFLOW without transport)
    if results and results.get('success_modflow') and sections.get("modeling"):
        print(f"\n[STEP {step_counter}] Executing: ex12_postprocessing_timeseries_modflow()")
        results = ex12_postprocessing_timeseries_modflow(results)
        step_counter += 1

    # STEP: TIMESERIES - COMPLETE (second generation: MODFLOW with MT3DMS, only if transport enabled and successful)
    if results and results.get('success_modflow') and sections.get("mt3dms") and results.get('success_mt3dms'):
        print(f"\n[STEP {step_counter}] Executing: ex12_postprocessing_timeseries_complete()")
        results = ex12_postprocessing_timeseries_complete(results)
        step_counter += 1

    # STEP 10: Plotting - EX12/EX09 only (use monolithic plot_ex12 module)
    plots_config = CONFIG.get("plots", {})
    example_key = results.get('example_key', CONFIG["example"]) if results else CONFIG["example"]

    # Only use monolithic plot block for ex12 and ex09
    if example_key in ["ex12", "ex09"] and results and sections.get("plot") and any(plots_config.values()):
        print(f"\n[STEP {step_counter}] Executing: Plots")
        print("\n" + "="*70)
        print("EXAMPLE 12 - PLOTTING".center(70))
        print("="*70)

        if results.get('success_modflow'):
            from plot_ex12 import (plot_cross_section, plot_streamflow, plot_piezometry,
                                   plot_pathlines, plot_concentration, plot_2d, plot_3d,
                                   plot_interactive_cross_section, plot_web_animation)

            # Get plot parameters from PARAMS based on example
            example_key = results.get('example_key', CONFIG["example"])
            plot_params = PARAMS.get(example_key, {}).get("plot_params", {})

            # Extract parameters with defaults
            factor = plot_params.get("factor", 30)
            vers = 'TRANS1'

            # Plot cross-section
            if plots_config.get("cross_section", True):
                print("  ✓ Plotting cross-section")
                plot_cross_section(results.get('geographic'),
                                 results.get('stable_folder'),
                                 results.get('simulations_folder'),
                                 results.get('model_name'))

            # Plot streamflow
            if plots_config.get("streamflow", True):
                print("  ✓ Plotting streamflow")
                plot_streamflow(results.get('geographic'),
                              results.get('data_path'),
                              results.get('simulations_folder'),
                              vers,
                              factor=factor)

            # Plot piezometry
            if plots_config.get("piezometry", True):
                print("  ✓ Plotting piezometry")
                plot_piezometry(results.get('geographic'),
                              results.get('simulations_folder'),
                              vers,
                              factor=factor)

            # Plot pathlines
            if plots_config.get("pathlines", True):
                print("  ✓ Plotting pathlines")
                plot_pathlines(results.get('geographic'),
                             results.get('stable_folder'),
                             results.get('simulations_folder'),
                             results.get('model_name'))

            # Plot concentration
            if plots_config.get("concentration", True) and results.get('concobj_1c_fil_surf') is not None:
                print("  ✓ Plotting concentration")
                plot_concentration(results.get('geographic'),
                                 results.get('hydrography'),
                                 results.get('stable_folder'),
                                 results.get('simulations_folder'),
                                 results.get('model_name'),
                                 results.get('model_modflow'),
                                 results.get('model_mt3dms'),
                                 results.get('R_mm_day'),
                                 vers=vers,
                                 factor=factor)

            # Plot 2D
            if plots_config.get("plot_2d", False):
                print("  ✓ Plotting 2D visualization")
                plot_2d(results.get('initializing'),
                       results.get('geographic'),
                       results.get('hydrography'),
                       results.get('model_name'))

            # Plot 3D
            if plots_config.get("plot_3d", False):
                print("  ✓ Plotting 3D visualization")
                plot_3d(results.get('initializing'),
                       results.get('geographic'),
                       results.get('hydrography'),
                       results.get('model_name'))

            # Plot interactive cross-section
            if plots_config.get("interactive_cross_section", True):
                print("  ✓ Plotting interactive cross-section")
                plot_interactive_cross_section(results.get('initializing'),
                                             results.get('geographic'),
                                             results.get('hydrography'),
                                             results.get('stable_folder'),
                                             results.get('simulations_folder'),
                                             results.get('model_name'))
        else:
            print("  ⚠ Skipping plots (MODFLOW failed)")

        print("\n  ✓ All requested plots completed\n")
        step_counter += 1

    # STEP 11: Web animation
    plots_config = CONFIG.get("plots", {})
    if results and plots_config.get("web_animation", False) and results.get('success_modflow'):
        print(f"\n[STEP {step_counter}] Executing: Web animation")
        from plot import plot_web_animation
        try:
            plot_web_animation(results.get('simulations_folder'),
                             results.get('model_name'),
                             vers='TRANS1', figsize=(1600, 900))
        except FileNotFoundError as e:
            print(f"  ⚠ Web animation skipped: {e}")
        step_counter += 1
    elif plots_config.get("web_animation", False) and not results.get('success_modflow'):
        print(f"\n[STEP {step_counter}] ⚠ Skipping animation (MODFLOW failed)")
        step_counter += 1

    # Final summary
    print("\n" + "="*70)
    print("EXECUTION COMPLETED".center(70))
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
        print("\n\n Interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n  Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
