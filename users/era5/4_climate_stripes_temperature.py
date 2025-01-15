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

#%% Select the directory 
folder_path = './t2m'
name = 't2m_annual_mean.csv'
file = os.path.join(folder_path, name)


#%%Then we define our time limits, our reference period for the neutral color 
#and the range around it for maximum saturation.
FIRST = 1941
LAST = 2023  # inclusive

#%%Here we use pandas to read the fixed width text file, only the first two columns, 
#which are the year and the deviation from the mean from 1961 to 1990.
df = pd.read_csv(file, index_col=0)

#%% COmpute the deviation from the mean accordinf to a reference period
start_ref = 1960
end_ref = 2000
mean_ref = df.loc[start_ref:end_ref]
mean_ref = mean_ref.mean()
df['anomaly'] = df['t2m'] - mean_ref.iloc[0]

# Reference period for the center of the color scale
LIM = 2.5 # degrees
anomaly = df.loc[FIRST:LAST, 'anomaly'].dropna()
reference = anomaly.loc[start_ref:end_ref].mean()

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
col.set_clim(reference - LIM, reference + LIM)
ax.add_collection(col)

ax.set_ylim(0, 1)
ax.set_xlim(FIRST, LAST + 1)

fig.savefig('./figures/warming-stripes.png')