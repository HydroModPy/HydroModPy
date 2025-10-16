def plot_dem_hillshade_stream(data_path, stable_folder, dem_path, id_name, watershed_name):
    """
    Plot hillshade, elevation (color), and stream network over the watershed extent.
    """
    import os
    import geopandas as gpd
    import rasterio
    from rasterio.transform import array_bounds
    from matplotlib.colors import LightSource
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    import numpy as np
    from scipy.ndimage import gaussian_filter

    watershed_fp = os.path.join(stable_folder, 'geographic', 'watershed.shp')
    watershed_box_fp = os.path.join(stable_folder, 'geographic', 'watershed_box.shp')
    stream_name = 'stream_network' + id_name + '.shp'
    stream_fp = os.path.join(data_path, '_sites', id_name, stream_name)

    # Load watershed box and stream network
    watershed_box = gpd.read_file(watershed_box_fp)
    watershed = gpd.read_file(watershed_fp)

    if not os.path.exists(stream_fp):
        print(f"Stream file '{stream_fp}' not found. Using default stream file instead.")
        # stream_fp = os.path.join(data_path, '_hydrology', 'EcrRiv_c_tr_alps_pyr.shp')
        stream_fp = os.path.join(data_path, '_hydrology', 'euhydro_v013_alps.gpkg')
        if not os.path.exists(stream_fp):
            raise FileNotFoundError(f"Backup stream file '{stream_fp}' is not found.")
    
    stream = gpd.read_file(stream_fp)

    # Load full DEM without clipping
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

    # Plot
    fig, ax = plt.subplots(figsize=(10, 10))

    # Hillshade overlay
    ax.imshow(hillshade, cmap='Greys', extent=extent, origin='upper', alpha=1)

    # DEM as color image with colorbar
    dem_cmap = plt.cm.terrain
    min_elevation = 0
    max_elevation = 4000
    im = ax.imshow(dem, cmap=dem_cmap, extent=extent, origin='upper', alpha=0.75,
                   vmin=min_elevation, vmax=max_elevation)
    cbar = plt.colorbar(im, ax=ax, orientation='vertical', shrink=0.7, label='Elevation (m)')

    # Stream network
    stream.plot(ax=ax, color='blue', linewidth=2)

    # Watershed outline
    watershed.plot(ax=ax, facecolor='none', edgecolor='red', linewidth=2)

    # Set plot bounds to the watershed_box + margin
    minx, miny, maxx, maxy = watershed_box.total_bounds
    xdist = maxx - minx
    ydist = maxy - miny
    f = 0.1  # margin fraction
    ax.set_xlim(minx - f * xdist, maxx + f * xdist)
    ax.set_ylim(miny - f * ydist, maxy + f * ydist)

    # Legend
    legend_elements = [
        Line2D([0], [0], color='blue', lw=2, label='Streams'),
        Line2D([0], [0], color='red', lw=2, label='Watershed boundary')
    ]
    ax.legend(handles=legend_elements, title="Legend", loc='lower right', fontsize=11, title_fontsize=12)
    ax.set_title(f'{watershed_name}', fontsize=14, fontweight='bold', loc='center')

    plt.tight_layout()

    # Save figure
    fig.savefig(os.path.join(stable_folder, '_figures', f'dem_stream{id_name}.png'), dpi=300)
    plt.close(fig)
    print(f"Elevation map for {id_name} saved!")

    return
