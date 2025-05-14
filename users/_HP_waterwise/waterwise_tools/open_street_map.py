import os
import geopandas as gpd
import matplotlib.pyplot as plt
import contextily as ctx


def open_street_map(stable_folder, id_name):
    """
    Plot the open street map over the watershed extent.
    """
    watershed_fp = os.path.join(stable_folder, 'geographic', 'watershed.shp')
    watershed_box_fp = os.path.join(stable_folder, 'geographic', 'watershed_box.shp')

    # Load watershed box and stream network
    watershed_box = gpd.read_file(watershed_box_fp)
    watershed = gpd.read_file(watershed_fp)

    watershed = watershed.to_crs(epsg=3857)  # Convert to Web Mercator projection for compatibility with OSM
    
    # Plot the watershed
    fig, ax = plt.subplots(figsize=(10, 10))
    watershed.plot(ax=ax, facecolor='none', edgecolor='red', linewidth=2)
    
    # Add OpenStreetMap basemap
    ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik)
    
    # Show the plot
    plt.show()

    # Set bounds
    minx, miny, maxx, maxy = watershed_box.total_bounds
    xdist = maxx-minx
    ydist = maxy-miny
    f = 0.1
    ax.set_xlim(minx-f*xdist, maxx+f*xdist)
    ax.set_ylim(miny-f*ydist, maxy+f*ydist)

    plt.tight_layout()
    plt.show()

    # Save figure
    fig.savefig(os.path.join(stable_folder, '_figures', f'open_street_map{id_name}.png'), dpi=300)
    # plt.close(fig)
    print(f"open_street_map for {id_name} saved!")

    return
