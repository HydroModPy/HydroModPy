# -*- coding: utf-8 -*-
"""
Created on Wed Mar 26 18:55:23 2025

@author: roquesc
"""

import os
import geopandas as gpd
import rasterio
import numpy as np
import matplotlib.pyplot as plt
from rasterio.mask import mask
from rasterio.transform import array_bounds
from matplotlib.colors import LightSource
from matplotlib.patches import Patch
from shapely.geometry import Polygon, MultiPolygon
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.collections import PatchCollection
from shapely.geometry import box
from scipy.ndimage import gaussian_filter

def process_geology_with_glim(data_path, stable_folder, dem_path, id_name, sites, site_num, watershed_name):
    print('I analyse the geology')

    # -- Paths
    geol_path = os.path.join(data_path, '_geology')
    watershed_fp = os.path.join(stable_folder, 'geographic', 'watershed.shp')
    watershed_box_fp = os.path.join(stable_folder, 'geographic', 'watershed_box.shp')
    stream_name = 'stream_network' + id_name + '.shp'
    stream_fp = os.path.join(data_path,'_sites', id_name, stream_name)
    glacier_fp = os.path.join(data_path, '_glaciers', 'rgi7_vector', 'rgi2000_v70_vector.shp')

    # -- Load spatial data
    watershed = gpd.read_file(watershed_fp)
    watershed_box = gpd.read_file(watershed_box_fp)

    if not os.path.exists(stream_fp):
        print(f"Stream file '{stream_fp}' not found. Using default stream file instead.")
        # stream_fp = os.path.join(data_path, '_hydrology', 'EcrRiv_c_tr_alps_pyr.shp')
        stream_fp = os.path.join(data_path, '_hydrology', 'euhydro_v013_alps.gpkg')
        if not os.path.exists(stream_fp):
            raise FileNotFoundError(f"Backup stream file '{stream_fp}' is not found.")
    
    stream = gpd.read_file(stream_fp)

    # Load full DEM 
    with rasterio.open(dem_path) as ra:
        if watershed_box.crs != ra.crs:
            watershed_box = watershed_box.to_crs(ra.crs)
        if stream.crs != ra.crs:
            stream = stream.to_crs(ra.crs)
        if watershed.crs != ra.crs:
            watershed = watershed.to_crs(ra.crs)

        dem = ra.read(1)
        bounds = ra.bounds
        transform = ra.transform
        
        # Smooth the DEM before hillshading
        dem = gaussian_filter(dem, sigma=1)  # try sigma between 1 and 2

        # Create hillshade
        ls = LightSource(azdeg=135, altdeg=45)
        hillshade = ls.hillshade(dem, vert_exag=2, dx=1, dy=1)

        # Get extent of the full DEM
        extent = [bounds.left, bounds.right, bounds.bottom, bounds.top]

    # -- Load and process geology
    geol = gpd.read_file(os.path.join(geol_path, 'GLiM_clip_EU.shp'))

    if geol.crs != watershed.crs:
        geol = geol.to_crs(watershed.crs)
        print("Reprojected EU geology to match watershed CRS.")

    geol_clipped = gpd.clip(geol, watershed)


    out_fp = os.path.join(stable_folder, 'geology', 'geology_watershed.shp')
    geol_clipped.to_file(out_fp)
    print(f"Clipped geology saved to: {out_fp}")

    geol_clipped = geol_clipped.dissolve(by='xx')

    geol_clipped['area'] = geol_clipped.geometry.area
    geol_clipped = geol_clipped.sort_values(by='area')

    watershed_polyg = gpd.read_file(watershed_fp)
    watershed_area = watershed_polyg.geometry.area.sum()
    row_index = sites.index[sites['ID_name'] == id_name].tolist()
    
    for index, row in geol_clipped.iterrows():
        lithology = str(index)
        percent_cover = row['area'] / watershed_area * 100
        sites.loc[row_index, lithology] = percent_cover

    # -- Load and clip glaciers
    glaciers = gpd.read_file(glacier_fp)
    if glaciers.crs != watershed.crs:
        glaciers = glaciers.to_crs(watershed.crs)
    glaciers_clipped = gpd.clip(glaciers, watershed)


    # -- Calculate glacier coverage
    glacier_area = glaciers_clipped.geometry.area.sum()
    watershed_area = watershed.geometry.area.sum()
    glacier_coverage = (glacier_area / watershed_area) * 100
    sites.loc[sites['ID_name'] == id_name, 'glacier_coverage'] = glacier_coverage
    print(f"Glacier coverage in the catchment: {glacier_coverage:.2f}%")

    # -- clip the geol for display
    # Compute buffered bounds
    minx, miny, maxx, maxy = watershed_box.total_bounds
    xdist = maxx - minx
    ydist = maxy - miny
    f = 0.1  # 10% buffer
    
    # Create the bounding box geometry (buffered mask)
    mask_geom = box(
        minx - f * xdist,
        miny - f * ydist,
        maxx + f * xdist,
        maxy + f * ydist
    )
    
    # Create a GeoDataFrame for the mask (same CRS as the shapefile to be clipped)
    mask_gdf = gpd.GeoDataFrame(geometry=[mask_geom], crs=watershed_box.crs)
    
    geol_clipped_display = gpd.clip(geol, mask_gdf)
    geol_clipped_display = geol_clipped_display.dissolve(by='xx')
    
    glaciers_clipped_box = gpd.clip(glaciers, mask_gdf)

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
    
    #display the glaciers
    # Plot glaciers with hatch pattern
   
    glaciers_patches = []
    for poly in glaciers_clipped_box.geometry:
        if poly.geom_type == 'Polygon':
            coords = np.array(poly.exterior.coords)[:, :2]  # Take only the first two columns (x, y)
            glaciers_patches.append(MplPolygon(coords, closed=True))
        elif poly.geom_type == 'MultiPolygon':
            for subpoly in poly.geoms:
                coords = np.array(subpoly.exterior.coords)[:, :2]  # Take only the first two columns (x, y)
                glaciers_patches.append(MplPolygon(coords, closed=True))
    
    # Create a PatchCollection with hatching
    glaciers_collection = PatchCollection(
        glaciers_patches,
        facecolor = 'none',
        edgecolor = 'cyan', #'#00796B',
        hatch = 'x',
        linewidth = 2,
        alpha = 1
    )
    
    # Add the PatchCollection to the plot
    ax.add_collection(glaciers_collection)
    
    # Set bounds
    ax.set_xlim(minx-f*xdist, maxx+f*xdist)
    ax.set_ylim(miny-f*ydist, maxy+f*ydist)

    legend_elements = [
        Patch(facecolor=glim_colors[key], edgecolor='k', label=glim_labels[key])
        for key in lithologies_present if key in glim_colors
    ]
    
    # Add glacier legend with hatching pattern
    legend_elements.append(Patch(facecolor='none', edgecolor='cyan', label='Glacier Cover', hatch='x'))
    
    ax.legend(handles=legend_elements, title="Lithology", loc='lower right', fontsize=11, title_fontsize=12)
    ax.set_title(f'{watershed_name}', fontsize=14, fontweight='bold', loc='center')
    plt.tight_layout()
    plt.show()
    
    fig.savefig(os.path.join(stable_folder, '_figures', f'geology_glim{id_name}.png'), dpi=300)
    plt.close(fig)
    print(f"geology map for {id_name} saved!")

    return sites
