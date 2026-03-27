# -*- coding: utf-8 -*-
"""
Plotting functions for Example 03 - Hydrographic network in steady state
Extracted and adapted from example_03_new.py for Launcher_Glob multi-example system

Author: HydroModPy Team
Date: 2026-02-25
"""

import os
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import imageio.v2 as imageio


# ============================================================================
# PLOT CROSS-SECTION - EXAMPLE 03
# ============================================================================

def plot_cross_section_ex03(results):
    """Plot cross-section DEM + watertable - from example_03_new.py lines 304-376

    Parameters
    ----------
    results : dict
        Dictionary containing:
        - stable_folder: Path to results_stable folder
        - simulations_folder: Path to results_simulations folder
        - list_model_modflow: List of MODFLOW models
        - list_model_names: List of model names
    """
    print("  • Plotting cross-sections (0.001 per loop)...")
    print(f"    [DEBUG] stable_folder={results.get('stable_folder')}")
    print(f"    [DEBUG] list_model_modflow count={len(results.get('list_model_modflow', []))}")

    try:
        stable_folder = results.get('stable_folder')
        simulations_folder = results.get('simulations_folder')
        geographic = results.get('geographic')
        list_model_modflow = results.get('list_model_modflow', [])
        list_model_names = results.get('list_model_names', [])

        if not list_model_modflow:
            print("    ⚠ No models to plot")
            return results

        if not stable_folder or not simulations_folder or not geographic:
            print("    ⚠ Paths or geographic object missing")
            return results

        # Use geographic object properties (like example_03_new.py)
        dem_path = geographic.watershed_dem
        if not os.path.exists(dem_path):
            print(f"    ⚠ DEM not found: {dem_path}")
            return results

        # Plot for first iteration only (to match example_03_new behavior)
        for idx, (model_name, model_modflow) in enumerate(zip(list_model_names, list_model_modflow)):
            if idx == 0:  # Only plot first model as in example_03_new
                fig, ax = plt.subplots(1, 1, figsize=(5, 3), dpi=300)

                dem_data = imageio.imread(dem_path)
                dem_data = np.ma.masked_where(dem_data < 0, dem_data)

                wt_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                                      r'_postprocess/_rasters/watertable_elevation_t(0).tif'))
                wt_data = np.ma.masked_where(wt_data < 0, wt_data)

                river_data = imageio.imread(os.path.join(stable_folder, 'hydrography',
                                                         'regional stream network.tif'))

                xvalues = np.linspace(-1, 1, dem_data.shape[1])
                yvalues = np.linspace(-1, 1, dem_data.shape[0])
                xx, yy = np.meshgrid(xvalues, yvalues)

                cur_x = dem_data.shape[1] / 2

                dem_prof = dem_data.astype(float)
                dem_prof[dem_prof < 0] = np.nan
                dem_v_plot = dem_prof[:, int(cur_x)]
                dem_v_plot[dem_v_plot == 0] = np.nan

                wt_prof = wt_data.astype(float)
                wt_prof[wt_prof < 0] = np.nan
                wt_v_plot = wt_prof[:, int(cur_x)]
                wt_v_plot[wt_v_plot == 0] = np.nan

                # Watertable fill
                wt_v_fill = ax.fill_between(np.arange(xx.shape[0]) * 75,
                                            dem_v_plot - 30, wt_v_plot,
                                            color='dodgerblue', alpha=0.5, lw=0)
                # Watertable line
                w_prof = ax.plot(np.arange(xx.shape[0]) * 75, wt_v_plot, color='navy', lw=1)

                # Unsaturated fill
                wt_v_fill = ax.fill_between(np.arange(xx.shape[0]) * 75,
                                            wt_v_plot, dem_v_plot,
                                            color='saddlebrown', alpha=0.5, lw=0)
                # Unsaturated line
                d_prof = ax.plot(np.arange(xx.shape[0]) * 75, dem_v_plot, 'saddlebrown', lw=1.5)

                # No-flow zone fill
                ax.fill_between(np.arange(xx.shape[0]) * 75,
                                0, dem_v_plot - 30,
                                color='lightgrey', alpha=1, lw=0, zorder=10)
                # No-flow zone line
                ax.plot(np.arange(xx.shape[0]) * 75, dem_v_plot - 30, color='dimgray', lw=1.5)

                ax.set_xlim(1000, 4000)
                ax.set_ylim(85, 130)
                ax.set_yticks([90, 100, 110, 120, 130])
                ax.set_xlabel('Distance [m]')
                ax.set_ylabel('Elevation [m]')
                ax.set_title('K = ' + '{:.2e}'.format(model_modflow.hk.mean() / 24 / 3600) + ' m/s')

                fig.tight_layout()

                # Save figure
                figure_folder = os.path.join(simulations_folder, model_name, '_postprocess/_figures')
                os.makedirs(figure_folder, exist_ok=True)
                fig.savefig(os.path.join(figure_folder, 'cross_section.png'), bbox_inches='tight')

                plt.close(fig)

    except Exception as e:
        print(f"    ✗ Cross-section plot error: {e}")
        import traceback
        traceback.print_exc()

    return results


# ============================================================================
# PLOT MAP - EXAMPLE 03
# ============================================================================

def plot_map_ex03(results):
    """Plot map with DEM and seepage areas - from example_03_new.py lines 381-456

    Parameters
    ----------
    results : dict
        Dictionary containing:
        - stable_folder: Path to results_stable folder
        - simulations_folder: Path to results_simulations folder
        - list_model_modflow: List of MODFLOW models
        - list_model_names: List of model names
    """
    print("  • Plotting maps (0.001 per loop)...")

    try:
        stable_folder = results.get('stable_folder')
        simulations_folder = results.get('simulations_folder')
        geographic = results.get('geographic')
        list_model_modflow = results.get('list_model_modflow', [])
        list_model_names = results.get('list_model_names', [])

        if not list_model_modflow:
            print("    ⚠ No models to plot")
            return results

        if not stable_folder or not simulations_folder or not geographic:
            print("    ⚠ Paths or geographic object missing")
            return results

        # Use geographic object properties (like example_03_new.py)
        dem_path = geographic.watershed_box_buff_dem
        contour_path = geographic.watershed_contour_tif

        if not os.path.exists(dem_path):
            print(f"    ⚠ DEM not found: {dem_path}")
            return results

        # Plot for first iteration only
        for idx, (model_name, model_modflow) in enumerate(zip(list_model_names, list_model_modflow)):
            if idx == 0:  # Only plot first model
                fig, ax = plt.subplots(1, 1, figsize=(5, 3), dpi=300)

                dem_data = imageio.imread(dem_path)
                dem_data = np.ma.masked_where(dem_data < 0, dem_data)

                contour = imageio.imread(contour_path) if os.path.exists(contour_path) else None
                if contour is not None:
                    contour = np.ma.masked_where(contour < 0, contour)

                obs_river_data = imageio.imread(os.path.join(stable_folder, 'hydrography',
                                                             'regional stream network.tif'))
                obs_river_data = np.ma.masked_where(obs_river_data < 0, obs_river_data)

                seep_river_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                                              r'_postprocess/_rasters/seepage_areas_t(0).tif'))
                seep_river_data = np.ma.masked_where(seep_river_data <= 0, seep_river_data)

                sim_river_data = imageio.imread(os.path.join(simulations_folder, model_name,
                                                             r'_postprocess/_rasters/accumulation_flux_t(0).tif'))
                sim_river_data = np.ma.masked_where(sim_river_data <= 0, sim_river_data)

                im_dem = ax.imshow(dem_data, alpha=0.5, cmap='Greys')
                if contour is not None:
                    im_cont = ax.imshow(contour, alpha=1, cmap=mpl.colors.ListedColormap('k'))
                im_obs = ax.imshow(obs_river_data, alpha=1, cmap=mpl.colors.ListedColormap('navy'))
                im_sim = ax.imshow(sim_river_data, cmap=mpl.colors.ListedColormap('red'), alpha=0.7)
                im_seep = ax.imshow(seep_river_data, cmap=mpl.colors.ListedColormap('darkorange'), alpha=0.7)

                ax.set_xlabel('X [pixels]')
                ax.set_ylabel('Y [pixels]')
                ax.set_title('K = ' + '{:.2e}'.format(model_modflow.hk.mean() / 24 / 3600) + ' m/s')

                fig.tight_layout()

                # Save figure
                figure_folder = os.path.join(simulations_folder, model_name, '_postprocess/_figures')
                os.makedirs(figure_folder, exist_ok=True)
                fig.savefig(os.path.join(figure_folder, 'map.png'), bbox_inches='tight')

                plt.close(fig)

    except Exception as e:
        print(f"    ✗ Map plot error: {e}")
        import traceback
        traceback.print_exc()

    return results


# ============================================================================
# PLOT GRAPH - EXAMPLE 03
# ============================================================================

def plot_graph_ex03(results):
    """Plot conductivity vs seepage areas - from example_03_new.py lines 459-474

    Parameters
    ----------
    results : dict
        Dictionary containing model and simulation information
    """
    print("  • Plotting graph (K vs drainage density)...")

    try:
        simulations_folder = results.get('simulations_folder')
        list_model_modflow = results.get('list_model_modflow', [])
        list_model_names = results.get('list_model_names', [])

        if not list_model_modflow:
            print("    ⚠ No models to plot")
            return results

        if not simulations_folder:
            print("    ⚠ simulations_folder not provided")
            return results

        fig, ax = plt.subplots(1, 1, figsize=(5, 4), dpi=300)

        for model_name, model_modflow in zip(list_model_names, list_model_modflow):
            csv_path = os.path.join(simulations_folder, model_name,
                                   '_postprocess', '_timeseries', '_simulated_timeseries.csv')
            if os.path.exists(csv_path):
                simul_csv = pd.read_csv(csv_path, sep=';')

                ax.plot(model_modflow.hk.mean() / 24 / 3600,
                        simul_csv['seepage_areas'].iloc[-1] if 'seepage_areas' in simul_csv.columns else 0,
                        marker='o', ms=8, lw=0, color='k')
            else:
                print(f"    ⚠ CSV not found: {csv_path}")

        ax.set_xscale('log')
        ax.set_xlabel('K [m/s]')
        ax.set_ylabel('Drainage density [%]')

        fig.tight_layout()

        # Save figure
        figure_folder = os.path.join(simulations_folder, '_postprocess', '_figures')
        os.makedirs(figure_folder, exist_ok=True)
        fig.savefig(os.path.join(figure_folder, 'graph_drainage_density.png'), bbox_inches='tight')

        plt.close(fig)

    except Exception as e:
        print(f"    ✗ Graph plot error: {e}")
        import traceback
        traceback.print_exc()

    return results
