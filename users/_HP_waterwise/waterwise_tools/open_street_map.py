import os
import geopandas as gpd
import matplotlib.pyplot as plt
import contextily as ctx
from matplotlib.lines import Line2D

def open_street_map(stable_folder, id_name, watershed_name):
    """
    Plot the open street map over the watershed extent and save the figure properly.
    """
    # Paths
    watershed_fp = os.path.join(stable_folder, 'geographic', 'watershed.shp')
    watershed_box_fp = os.path.join(stable_folder, 'geographic', 'watershed_box.shp')

    # Load data
    watershed = gpd.read_file(watershed_fp)
    watershed_box = gpd.read_file(watershed_box_fp)

    # Reproject to Web Mercator for basemap
    watershed = watershed.to_crs(epsg=3857)
    watershed_box = watershed_box.to_crs(epsg=3857)

    # Create plot
    fig, ax = plt.subplots(figsize=(10, 10))
    watershed.plot(ax=ax, facecolor='none', edgecolor='red', linewidth=2)

    # Set bounds BEFORE adding the basemap
    minx, miny, maxx, maxy = watershed_box.total_bounds
    xdist = maxx - minx
    ydist = maxy - miny
    f = 0.1
    ax.set_xlim(minx - f * xdist, maxx + f * xdist)
    ax.set_ylim(miny - f * ydist, maxy + f * ydist)

    # Add basemap
    ctx.add_basemap(
        ax,
        source=ctx.providers.OpenStreetMap.Mapnik,
        crs=watershed.crs,
        reset_extent=False  # IMPORTANT: prevent auto-reset of bounds
    )

    # Add legend
    ax.legend(
        [Line2D([0], [0], color='red', lw=2)],
        ['Watershed boundary'],
        loc='lower right',
        fontsize=11,
        title='Legend',
        title_fontsize=12
    )

    ax.set_title(f'{watershed_name}', fontsize=14, fontweight='bold', loc='center')
    
    # Tight layout + save
    plt.tight_layout()
    fig_path = os.path.join(stable_folder, '_figures', f'open_street_map{id_name}.png')
    fig.savefig(fig_path, dpi=300, bbox_inches='tight')  # Add bbox_inches to capture full map
    plt.close(fig)

    print(f"open_street_map for {id_name} saved to: {fig_path}")
