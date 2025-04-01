import os
import geopandas as gpd
import rasterio
from rasterio.mask import mask
from rasterio.transform import array_bounds
from matplotlib.colors import LightSource
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

def plot_dem_hillshade_stream(data_path, stable_folder, dem_path, watershed_name):
    """
    Plot hillshade, elevation (color), and stream network over the watershed extent.
    """
    watershed_fp = os.path.join(stable_folder, 'geographic', 'watershed.shp')
    watershed_box_fp = os.path.join(stable_folder, 'geographic', 'watershed_box.shp')
    stream_name = 'stream_network' + watershed_name[1:] + '.shp'
    stream_fp = os.path.join(data_path, watershed_name, stream_name)

    # Load watershed box and stream network
    watershed_box = gpd.read_file(watershed_box_fp)
    watershed = gpd.read_file(watershed_fp)
    stream = gpd.read_file(stream_fp)

    # Load and clip DEM
    with rasterio.open(dem_path) as ra:
        if watershed_box.crs != ra.crs:
            watershed_box = watershed_box.to_crs(ra.crs)

        clipped_dem, clipped_transform = mask(ra, watershed_box.geometry, crop=True)
        dem = clipped_dem[0]

        # Create hillshade
        ls = LightSource(azdeg=135, altdeg=45)
        hillshade = ls.hillshade(dem, vert_exag=2, dx=1, dy=1)

        # Compute extent for plotting
        height, width = dem.shape
        bounds = array_bounds(height, width, clipped_transform)
        extent = [bounds[0], bounds[2], bounds[1], bounds[3]]

    # Plot
    fig, ax = plt.subplots(figsize=(10, 10))

    # Hillshade overlay
    ax.imshow(hillshade, cmap='Greys', extent=extent, origin='upper', alpha=1)

    # DEM as color image with colorbar
    dem_cmap = plt.cm.terrain
    im = ax.imshow(dem, cmap=dem_cmap, extent=extent, origin='upper', alpha=0.75)
    cbar = plt.colorbar(im, ax=ax, orientation='vertical', shrink=0.7, label='Elevation (m)')

    # Stream network
    stream = stream.to_crs(watershed_box.crs)
    stream.plot(ax=ax, color='blue', linewidth=2)

    # Watershed outline
    watershed = watershed.to_crs(watershed_box.crs)
    watershed.plot(ax=ax, facecolor='none', edgecolor='red', linewidth=2)

    # Set bounds
    minx, miny, maxx, maxy = watershed_box.total_bounds
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)

    # Legend
    legend_elements = [
        Line2D([0], [0], color='blue', lw=2, label='Streams'),
        Line2D([0], [0], color='red', lw=2, label='Watershed boundary')
    ]
    ax.legend(handles=legend_elements, title="legend", loc='lower right', fontsize=11, title_fontsize=12)

    plt.tight_layout()
    plt.show()

    # Save figure
    fig.savefig(os.path.join(stable_folder, '_figures', f'dem_stream{watershed_name[1:]}.png'), dpi=300)
    print(f"elevation map for {watershed_name[2:]} saved!")

    return
