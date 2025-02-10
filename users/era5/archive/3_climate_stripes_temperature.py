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
output_folder = os.path.join(base_path,catch_name)
#r'\\vert\CHYN_OBSERVATOIRE_POSCHIAVINO\_Alps\_public_database\_climate\era5\_hourly\extract'
polygon_path = os.path.join(polygon_folder, 'catchment_bnd_urse_streamgauge_EPSG3035.shp')
variables = ['2m_temperature', 'snow_depth', 'total_precipitation', 'forecast_albedo']

variable = ['2m_temperature']

# Ensure the output folders exist
os.makedirs(output_folder, exist_ok=True)
fig_folder = os.path.join(output_folder, 'fig')
os.makedirs(fig_folder, exist_ok=True)

name = variable[0] + '.csv'
file = os.path.join(output_folder, name)

# hourly_df = pd.read_csv(file, index_col=4)
# hourly_df.index = pd.to_datetime(hourly_df.index)



#%%Here we use pandas to read the fixed width text file, only the first two columns, 
#which are the year and the deviation from the mean from 1961 to 1990.
df = pd.read_csv(file, index_col=4)
df.index = pd.to_datetime(df.index)

#%%Then we define our time limits, our reference period for the neutral color 
#and the range around it for maximum saturation.
FIRST = df.index.min()
LAST = df.index.max()  # inclusive

#%% COmpute the deviation from the mean accordinf to a reference period
start_ref = df.index.min()
end_ref = pd.Timestamp('2000-12-31')
mean_ref = df['mean']
mean_ref = mean_ref[(mean_ref.index >= start_ref) & (mean_ref.index <= end_ref)].mean()
# mean_ref = mean_ref.mean()
df['anomaly'] = df['mean'] - mean_ref

# Reference period for the center of the color scale
LIM = 2.5 # degrees
anomaly = df['anomaly']
anomaly = anomaly[(anomaly.index >= FIRST) & (anomaly.index <= LAST)]
anomaly = anomaly.dropna()


#%% the colors in this colormap come from http://colorbrewer2.org

# the 8 more saturated colors from the 9 blues / 9 reds

cmap = ListedColormap([
    '#08306b', '#08519c', '#2171b5', '#4292c6',
    '#6baed6', '#9ecae1', '#c6dbef', '#deebf7',
    '#fee0d2', '#fcbba1', '#fc9272', '#fb6a4a',
    '#ef3b2c', '#cb181d', '#a50f15', '#67000d',
])

#%% We create a figure with a single axes object that fills the full area of the figure and does not have any axis ticks or labels.

fig = plt.figure(figsize=(10, 1))

ax = fig.add_axes([0, 0, 1, 1])
ax.set_axis_off()

#%% Finally, we create bars for each year, assign the data, colormap and color limits and add it to the axes.

# create a collection with a rectangle for each year

col = PatchCollection([
    Rectangle((y, 0), 1, 1)
    for y in range(FIRST, LAST + 1)
])

# set data, colormap and color limits

col.set_array(anomaly)
col.set_cmap(cmap)
col.set_clim(mean_ref - LIM, mean_ref + LIM)
ax.add_collection(col)

ax.set_ylim(0, 1)
ax.set_xlim(FIRST, LAST + 1)

name_fig = variable[0] + '_stripes.png'
fig_name = os.path.join(fig_folder,name_fig)
fig.savefig(fig_name)