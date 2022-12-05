# coding:utf-8
"""

"""

#%% LIBRAIRIES

import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.font_manager import FontProperties
# Hydromodpy
from tools import toolbox

#%% COLORS

color_dict = {'RCP2.6':'dodgerblue',
              'RCP8.5':'red',
              'RCP4.5':'salmon'}

#%% FUNCTIONS

def display_data(data, figure_folder, value):
    fontprop = toolbox.plot_params(15,15,18,20)
    fig = plt.figure()
    
    for sce in data:
        d = data[sce].index.values
        data[sce]['median'].plot(c=color_dict[sce], label=sce+': median values')
        plt.fill_between(d , data[sce]['std high'], data[sce]['std low'],facecolor=color_dict[sce], alpha=0.2, label=sce +': 5th and 95th perc')
        #data[sce]['5th per'].plot(c=color_dict[sce],ls='--', label=sce)
        #data[sce]['95th per'].plot(c=color_dict[sce],ls='--', label=sce)

    plt.legend(loc='best')
    plt.xlabel('Date')
    if value =='RMSL':
        plt.ylabel('Mean Sea Level [m]')
    if value =='RSL':
        plt.ylabel('Rise Sea Level [m]')
    
    plt.tight_layout()
    name_out = figure_folder + 'plot'
    fig.savefig(name_out + '.png', dpi=300, bbox_inches='tight')

#%% NOTES

