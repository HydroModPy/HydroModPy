# -*- coding: utf-8 -*-
"""
Created on Wed Mar 26 18:55:23 2025

@author: roquesc
"""

import os
import geopandas as gpd
import rasterio
from rasterio.mask import mask
from rasterio.transform import array_bounds
from matplotlib.colors import LightSource
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

def process_geology_with_glim(data_path, stable_folder, dem_path, watershed_name, site, site_num):
    print('I analyse the geology')

    # -- Paths
    geol_path = os.path.join(data_path, '_geology')
    watershed_fp = os.path.join(stable_folder, 'geographic', 'watershed.shp')
    watershed_box_fp = os.path.join(stable_folder, 'geographic', 'watershed_box.shp')
    stream_name = 'stream_network' + watershed_name[1:] + '.shp'
    stream_fp = os.path.join(data_path, watershed_name, stream_name)

    # -- Load spatial data
    watershed = gpd.read_file(watershed_fp)
    watershed_box = gpd.read_file(watershed_box_fp)
    stream = gpd.read_file(stream_fp)

    # -- Load and clip DEM
    with rasterio.open(dem_path) as ra:
        if watershed_box.crs != ra.crs:
            watershed_box = watershed_box.to_crs(ra.crs)

        clipped_dem, clipped_transform = mask(ra, watershed_box.geometry, crop=True)
        dem = clipped_dem[0]

        #print("DEM min/max:", dem.min(), dem.max())

        ls = LightSource(azdeg=135, altdeg=45)
        hillshade = ls.hillshade(dem, vert_exag=2, dx=1, dy=1)

        height, width = dem.shape
        bounds = array_bounds(height, width, clipped_transform)
        extent = [bounds[0], bounds[2], bounds[1], bounds[3]]

    # -- Load and process geology
    geol = gpd.read_file(os.path.join(geol_path, 'GLiM_clip_EU.shp'))

    if geol.crs != watershed.crs:
        geol = geol.to_crs(watershed.crs)
        print("Reprojected EU geology to match watershed CRS.")

    geol_clipped = gpd.clip(geol, watershed)
    geol_clipped_display = gpd.clip(geol, watershed_box)

    out_fp = os.path.join(stable_folder, 'geology', 'geology_watershed.shp')
    geol_clipped.to_file(out_fp)
    print(f"Clipped geology saved to: {out_fp}")

    geol_clipped = geol_clipped.dissolve(by='xx')
    geol_clipped_display = geol_clipped_display.dissolve(by='xx')
    geol_clipped['area'] = geol_clipped.geometry.area
    geol_clipped = geol_clipped.sort_values(by='area')

    watershed_polyg = gpd.read_file(watershed_fp)
    watershed_area = watershed_polyg.geometry.area.sum()

    for index, row in geol_clipped.iterrows():
        lithology = str(index)
        percent_cover = row['area'] / watershed_area * 100
        site.at[site_num, lithology] = percent_cover

    # -- GLiM color palette
    glim_colors = {
        'ss': '#fdbf6f', 'sm': '#ff7f00', 'sc': '#a6cee3', 'su': '#ffff99',
        'mt': '#b2df8a', 'py': '#cab2d6', 'vb': '#6a3d9a', 'va': '#ff33cc',
        'pb': '#1f78b4', 'pa': '#e31a1c', 'ev': '#b15928', 'nd': '#999999',
        'wb': '#377eb8', 'ig': '#ffffff'
    }

    glim_labels = {
        'ss': 'Siliciclastic', 'sm': 'Mixed Sediments', 'sc': 'Carbonates',
        'su': 'Unconsolidated', 'mt': 'Metamorphics', 'py': 'Pyroclastics',
        'vb': 'Basic Volcanics', 'va': 'Acid Volcanics', 'pb': 'Basic Plutonics',
        'pa': 'Acid Plutonics', 'ev': 'Evaporites', 'nd': 'No Data',
        'wb': 'Water Bodies', 'ig': 'Glaciers'
    }

    # -- Plotting
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.imshow(hillshade, cmap='Greys', extent=extent, origin='upper', alpha=1)

    geol_clipped_display = geol_clipped_display.reset_index()
    lithologies_present = geol_clipped_display['xx'].unique()

    for lith in lithologies_present:
        if lith in glim_colors:
            subset = geol_clipped_display[geol_clipped_display['xx'] == lith]
            subset.plot(ax=ax, facecolor=glim_colors[lith], edgecolor='k', linewidth=0.2, alpha=0.75)

    watershed.plot(ax=ax, facecolor='none', edgecolor='red', linewidth=2)
    stream.plot(ax=ax, facecolor='none', edgecolor='blue', linewidth=2)

    minx, miny, maxx, maxy = watershed_box.total_bounds
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)

    legend_elements = [
        Patch(facecolor=glim_colors[key], edgecolor='k', label=glim_labels[key])
        for key in lithologies_present if key in glim_colors
    ]
    ax.legend(handles=legend_elements, title="Lithology", loc='lower right', fontsize=11, title_fontsize=12)
    plt.tight_layout()
    plt.show()
    
    fig.savefig(os.path.join(stable_folder, '_figures', f'geology_glim{watershed_name[1:]}.png'), dpi=300)
    print(f"geology map for {watershed_name[2:]} saved!")

    return site
