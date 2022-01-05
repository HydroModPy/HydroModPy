# -*- coding: utf-8 -*-
"""
Created on Mon Dec 20 08:08:53 2021

@author: ronan
"""

import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.font_manager import FontProperties

def plot_params(small,interm,medium,large):
    
    small = small
    interm = interm
    medium = medium
    large = large
    
    # mpl.rcParams['backend'] = 'wxAgg'
    mpl.style.use('classic')
    mpl.rcParams["figure.facecolor"] = 'white'
    mpl.rcParams['grid.color'] = 'darkgrey'
    mpl.rcParams['grid.linestyle'] = '-'
    mpl.rcParams['grid.alpha'] = 0.8
    mpl.rcParams['axes.axisbelow'] = True
    mpl.rcParams['axes.linewidth'] = 1.5
    mpl.rcParams['figure.dpi'] = 300
    mpl.rcParams['savefig.dpi'] = 300
    mpl.rcParams['patch.force_edgecolor'] = True
    mpl.rcParams['image.interpolation'] = 'nearest'
    mpl.rcParams['image.resample'] = True
    mpl.rcParams['axes.autolimit_mode'] = 'data' # 'round_numbers' # 
    mpl.rcParams['axes.xmargin'] = 0.05
    mpl.rcParams['axes.ymargin'] = 0.05
    mpl.rcParams['xtick.direction'] = 'in'
    mpl.rcParams['ytick.direction'] = 'in'
    mpl.rcParams['xtick.major.size'] = 5
    mpl.rcParams['xtick.minor.size'] = 3
    mpl.rcParams['xtick.major.width'] = 1.5
    mpl.rcParams['xtick.minor.width'] = 1
    mpl.rcParams['ytick.major.size'] = 5
    mpl.rcParams['ytick.minor.size'] = 1.5
    mpl.rcParams['ytick.major.width'] = 1.5
    mpl.rcParams['ytick.minor.width'] = 1
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
    mpl.rcParams.update({'mathtext.default': 'regular' })
    
    plt.rc('font', size=small)                         # controls default text sizes **font
    plt.rc('figure', titlesize=large)                   # fontsize of the figure title
    plt.rc('legend', fontsize=small)                     # legend fontsize
    plt.rc('axes', titlesize=medium, labelpad=10)        # fontsize of the axes title
    plt.rc('axes', labelsize=medium, labelpad=12)        # fontsize of the x and y labels
    plt.rc('xtick', labelsize=interm)                   # fontsize of the tick labels
    plt.rc('ytick', labelsize=interm)                   # fontsize of the tick labels
    plt.rc('font', family='arial')
    
    fontprop = FontProperties()
    fontprop.set_family('arial') # for x and y label
    fontdic = {'family' : 'arial', 'weight' : 'bold'} # for legend  

    return fontprop      
    