# -*- coding: utf-8 -*-
"""
Created on Wed Jan 29 18:04:16 2025

@author: delarueo
"""
import geopandas as gpd
import geodatasets
import folium

# Load the datasets
nybb = gpd.read_file(geodatasets.get_path("nybb"))
chicago = gpd.read_file(geodatasets.get_path("geoda.chicago_commpop"))
groceries = gpd.read_file(geodatasets.get_path("geoda.groceries")).explode(ignore_index=True)

# Explore NY Boroughs (nybb)
nybb.explore(
    column="BoroName",  # make choropleth based on "BoroName" column
    tooltip="BoroName",  # show "BoroName" value in tooltip (on hover)
    popup=True,  # show all values in popup (on click)
    tiles="CartoDB positron",  # use "CartoDB positron" tiles
    cmap="Set1",  # use "Set1" matplotlib colormap
    style_kwds=dict(color="black"),  # use black outline
)

# Explore Chicago Population (chicago)
m = chicago.explore(
    column="POP2010",  # make choropleth based on "POP2010" column
    scheme="naturalbreaks",  # use mapclassify's natural breaks scheme
    legend=True,  # show legend
    k=10,  # use 10 bins
    tooltip=False,  # hide tooltip
    popup=["POP2010", "POP2000"],  # show popup (on-click)
    legend_kwds=dict(colorbar=False),  # do not use colorbar
    name="chicago",  # name of the layer in the map
)

# Add Groceries Layer (groceries)
groceries.explore(
    m=m,  # pass the map object
    color="red",  # use red color on all points
    marker_kwds=dict(radius=5, fill=True),  # make marker radius 10px with fill
    tooltip="Address",  # show "name" column in the tooltip
    tooltip_kwds=dict(labels=False),  # do not show column label in the tooltip
    name="groceries",  # name of the layer in the map
)

# Use folium to add additional tile layer and layer control
folium.TileLayer("CartoDB positron", show=False).add_to(m)  # add CartoDB positron
folium.LayerControl().add_to(m)  # add layer control

# Save the map to an HTML file and display it in Spyder
map_path = "interactive_map.html"
m.save(map_path)

# In Spyder, open the map in the default web browser automatically
import webbrowser
webbrowser.open(map_path)


