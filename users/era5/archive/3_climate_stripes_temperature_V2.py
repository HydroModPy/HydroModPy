# -*- coding: utf-8 -*-
"""
Created on Mon May  6 18:22:42 2024

@author: roquesc

CLIMATE STRIPES
https://matplotlib.org/matplotblog/posts/warming-stripes/

"""

import os
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.collections import PatchCollection
from matplotlib.colors import ListedColormap
import pandas as pd

#%% Load your hourly temperature data 
# Define paths
base_path = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_Alps\_public_database\_climate\era5\_hourly'
polygon_folder = r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_poschiavino\_gis\bnd'
catch_name = 'urse'
output_folder = os.path.join(base_path, catch_name)
variables = ['2m_temperature', 'snow_depth', 'total_precipitation', 'forecast_albedo']

variable = ['2m_temperature']

# Ensure the output folders exist
os.makedirs(output_folder, exist_ok=True)
fig_folder = os.path.join(output_folder, 'fig')
os.makedirs(fig_folder, exist_ok=True)

name = variable[0] + '.csv'
file = os.path.join(output_folder, name)

#%% Read data
df = pd.read_csv(file, index_col=4)
df.index = pd.to_datetime(df.index)
df = df.resample('Y').mean()

#%% Define time limits and reference period
FIRST = df.index.min().year  # Convert to year
LAST = df.index.max().year   # Convert to year

# Compute the deviation from the mean according to a reference period
start_ref = df.index.min()
end_ref = pd.Timestamp('2000-12-31')

# Ensure the reference period is within the data range
if end_ref > df.index.max():
    end_ref = df.index.max()

mean_ref = df['mean'][(df.index >= start_ref) & (df.index <= end_ref)].mean()
df['anomaly'] = df['mean'] - mean_ref

# Reference period for the center of the color scale
LIM = 2.5  # degrees
anomaly = df['anomaly']
anomaly = anomaly[(df.index.year >= FIRST) & (df.index.year <= LAST)]
anomaly = anomaly.dropna()

#%% Define color map
cmap = ListedColormap([
    '#08306b', '#08519c', '#2171b5', '#4292c6',
    '#6baed6', '#9ecae1', '#c6dbef', '#deebf7',
    '#fee0d2', '#fcbba1', '#fc9272', '#fb6a4a',
    '#ef3b2c', '#cb181d', '#a50f15', '#67000d',
])

#%% Create the figure
fig = plt.figure(figsize=(10, 1))

ax = fig.add_axes([0, 0, 1, 1])
ax.set_axis_off()

# Create a collection with a rectangle for each year
col = PatchCollection([
    Rectangle((y, 0), 1, 1)
    for y in range(FIRST, LAST + 1)  # Use integer years
])

# Set data, colormap, and color limits
col.set_array(anomaly.values)  # Pass the anomaly values
col.set_cmap(cmap)
col.set_clim(-LIM, LIM)
ax.add_collection(col)

# Set the x and y limits for the plot
ax.set_ylim(0, 1)
ax.set_xlim(FIRST, LAST + 1)

# Save the figure
name_fig = variable[0] + '_stripes.png'
fig_name = os.path.join(fig_folder, name_fig)
fig.savefig(fig_name, dpi=300, bbox_inches='tight')
plt.show()
