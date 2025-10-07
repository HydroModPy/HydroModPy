
import os
import geopandas as gpd
import matplotlib.pyplot as plt
import contextily as ctx
from matplotlib.lines import Line2D

def google_satellite_map(data_path, stable_folder, id_name, watershed_name):
    """
    Plot a Google Satellite-style basemap over the watershed extent.
    """
    # Paths to shapefiles
    watershed_fp = os.path.join(stable_folder, 'geographic', 'watershed.shp')
    watershed_box_fp = os.path.join(stable_folder, 'geographic', 'watershed_box.shp')
    stream_name = 'stream_network' + id_name + '.shp'
    stream_fp = os.path.join(data_path, '_sites', id_name, stream_name)

    # Load shapefiles
    watershed_box = gpd.read_file(watershed_box_fp)
    watershed = gpd.read_file(watershed_fp)
    
    #load the stream
    
    if not os.path.exists(stream_fp):
        print(f"Stream file '{stream_fp}' not found. Using default stream file instead.")
        # stream_fp = os.path.join(data_path, '_hydrology', 'EcrRiv_c_tr_alps_pyr.shp')
        stream_fp = os.path.join(data_path, '_hydrology', 'euhydro_v013_alps.gpkg')
        if not os.path.exists(stream_fp):
            raise FileNotFoundError(f"Backup stream file '{stream_fp}' is not found.")
    
    stream = gpd.read_file(stream_fp)

    # Convert to Web Mercator projection (required by basemap tiles)
    watershed = watershed.to_crs(epsg=3857)
    watershed_box = watershed_box.to_crs(epsg=3857)
    stream = stream.to_crs(epsg = 3857)

    # Create plot
    fig, ax = plt.subplots(figsize=(10, 10))
    stream.plot(ax=ax, color='blue', linewidth=2)
    watershed.plot(ax=ax, facecolor='none', edgecolor='red', linewidth=2)

    # Define plot bounds with margin
    minx, miny, maxx, maxy = watershed_box.total_bounds
    xdist = maxx - minx
    ydist = maxy - miny
    f = 0.1  # margin fraction
    ax.set_xlim(minx - f * xdist, maxx + f * xdist)
    ax.set_ylim(miny - f * ydist, maxy + f * ydist)

    # Add satellite basemap (Esri Satellite = closest to Google Earth)
    ctx.add_basemap(ax, source=ctx.providers.Esri.WorldImagery)
    
    # Stream network
    stream.plot(ax=ax, color='blue', linewidth=2)

    # Optional: Add a legend
    # Legend
    legend_elements = [
        Line2D([0], [0], color='blue', lw=2, label='Streams'),
        Line2D([0], [0], color='red', lw=2, label='Watershed boundary')
    ]
    ax.legend(handles=legend_elements, title="Legend", loc='lower right', fontsize=11, title_fontsize=12)
    ax.set_title(f'{watershed_name}', fontsize=14, fontweight='bold', loc='center')

    # Save figure
    fig_path = os.path.join(stable_folder, '_figures', f'google_satellite_map{id_name}.png')
    fig.savefig(fig_path, dpi=300)
    plt.close(fig)
    print(f"Google satellite map for {id_name} saved to: {fig_path}")

    return
