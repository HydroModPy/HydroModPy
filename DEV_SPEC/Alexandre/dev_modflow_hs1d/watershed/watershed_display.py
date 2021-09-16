# -*- coding: utf-8 -*-
"""
Created on Tue Sep 14 18:07:38 2021

@author: Alexandre Gauvain
"""

# Librairies
import os
import pandas as pd
import numpy as np
from glob import glob
import threading
import geopandas as gpd
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)
import shutil
import sys
import imageio
import re
import deepdish as dd
from hydroeval import *
import gdal
import rasterio

# Plots
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.pylab as pl
from matplotlib.font_manager import FontProperties
from mpl_toolkits.axes_grid1 import make_axes_locatable

# Parameters plot : v2.0 to classic customized
# mpl.style.use('default')
# mpl.rcParams.update(mpl.rcParamsDefault)

# # # Classic
mpl.style.use('classic')
mpl.rcParams["figure.facecolor"] = 'white'
mpl.rcParams['grid.color'] = 'darkgrey'
mpl.rcParams['grid.linestyle'] = '-'
mpl.rcParams['grid.alpha'] = 0.8
mpl.rcParams['axes.axisbelow'] = True
mpl.rcParams['figure.dpi'] = 300
mpl.rcParams['savefig.dpi'] = 300
mpl.rcParams['patch.force_edgecolor'] = True
mpl.rcParams['image.interpolation'] = 'nearest'
mpl.rcParams['image.resample'] = True
mpl.rcParams['axes.autolimit_mode'] = 'data' # 'round_numbers'
# mpl.rcParams['axes.autolimit_mode'] = 'round_numbers' # 'data' 
mpl.rcParams['axes.xmargin'] = 0.1
mpl.rcParams['axes.ymargin'] = 0.1
mpl.rcParams['xtick.direction'] = 'in'
mpl.rcParams['ytick.direction'] = 'in'
mpl.rcParams['xtick.top'] = True
mpl.rcParams['ytick.right'] = True
mpl.rcParams['legend.numpoints'] = 1
mpl.rcParams['legend.scatterpoints'] = 1
mpl.rcParams['legend.edgecolor'] = 'grey'
mpl.rcParams['date.autoformatter.year'] = '%Y'
mpl.rcParams['date.autoformatter.month'] = '%Y-%m'
mpl.rcParams['date.autoformatter.day'] = '%Y-%m-%d'
mpl.rcParams['date.autoformatter.hour'] = '%H:%M'
mpl.rcParams['date.autoformatter.minute'] = '%H:%M:%S'
mpl.rcParams['date.autoformatter.second'] = '%H:%M:%S'

# Parameters size plot
smal = 8
medium = 16
large = 20

plt.rc('font', size=medium)                         # controls default text sizes **font
plt.rc('figure', titlesize=medium)                   # fontsize of the figure title
plt.rc('legend', fontsize=smal)                     # legend fontsize
plt.rc('axes', titlesize=medium, labelpad=8)        # fontsize of the axes title
plt.rc('axes', labelsize=medium, labelpad=12)        # fontsize of the x and y labels
plt.rc('xtick', labelsize=medium)                   # fontsize of the tick labels
plt.rc('ytick', labelsize=medium)                   # fontsize of the tick labels
plt.rcParams["font.family"] = "serif"

# Font label and legend properties
fontprop = FontProperties()
fontprop.set_family('serif') # for x and y label
fontdic = {'family' : 'serif'} # for legend

def watershed(geographic):
    