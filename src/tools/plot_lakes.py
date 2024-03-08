# -*- coding: utf-8 -*-
"""
Created on Mon Feb 12 01:46:55 2024

@author: coche
"""
#%% IMPORTS
import geoconvert as gc
import cwatplot as cwp
import numpy as np
import os
import datetime
import pandas as pd

#%% LOAD
x = 330975
y = 6780825
coords_ = (x, y)
epsg_coords_ = 2154

abaque = pd.read_csv(r"D:\2- Postdoc\2- Travaux\1- Veille\1- Biblio locale\14- Barrage\abaque Cheze\abaque_cheze_2020.csv",
                     sep = "\t",
                     header = 0,
                     names = ['level', 'volume'],
                     )

abaque_model = pd.read_csv(r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\6- Lacs et reservoirs\Cheze\bathymetry\reflexion bathymetrie\modeled_abaque_1m_v2extended.csv",
                           sep = "\t",
                           header = 0,
                           names = ['level', 'volume'],
                           )

levels_dict = dict()
volumes_dict = dict()
areas_dict = dict()
ds_dict = dict()
results = {'volume': volumes_dict,
           'level': levels_dict,
           'area': areas_dict}

dam_data_path = os.path.join(r"D:\2- Postdoc\2- Travaux\1- Veille", 
                             r"1- Biblio locale\14- Barrage",
                             "Documents_travail_Ronan\dam_data",
                             r"dam_cheze_volume_raw_2000-2022.csv")

volumes_dict['data'] = pd.read_csv(dam_data_path,
                                   sep = ";",
                                   header = 0,
                                   skiprows = 0,
                                   index_col = 'time',
                                   usecols = ['time', 'cheze'],
                                   parse_dates = True)

levels_dict['data'] = volumes_dict['data'].copy()
for t in levels_dict['data'].index[0:-1]:
    levels_dict['data'].loc[t] = abaque[abaque.volume < levels_dict['data'].loc[t].values[0]].iloc[-1].level

volumes_dict['data']['time'] = volumes_dict['data'].index
volumes_dict['data']['val'] = volumes_dict['data'].cheze

levels_dict['data']['time'] = levels_dict['data'].index
levels_dict['data']['val'] = levels_dict['data'].cheze


# =============================================================================
# run = 'Cheze_Dam_1.2'
# cheze_12 = gc.time_series(input_file = os.path.join(
#     r"C:\Users\coche\Documents\Dam_EBR\results\raw", run, 
#     r"results_simulations\base\_postprocess\_netcdf\watertable_elevation.nc"), 
#                       coords = coords_, epsg_coords = epsg_coords_, 
#                       epsg_data = 2154)
# 
# run = 'Cheze_Dam_1.7'
# cheze_17 = gc.time_series(input_file = os.path.join(
#     r"C:\Users\coche\Documents\Dam_EBR\results\raw", run, 
#     r"results_simulations\base\_postprocess\_netcdf\watertable_elevation.nc"), 
#                       coords = coords_, epsg_coords = epsg_coords_, 
#                       epsg_data = 2154)
# 
# run = 'Cheze_Dam_1.8'
# cheze_18 = gc.time_series(input_file = os.path.join(
#     r"C:\Users\coche\Documents\Dam_EBR\results\raw", run, 
#     r"results_simulations\base\_postprocess\_netcdf\watertable_elevation.nc"), 
#                       coords = coords_, epsg_coords = epsg_coords_, 
#                       epsg_data = 2154)
# 
# run = 'Cheze_Dam_1.9'
# cheze_19 = gc.time_series(input_file = os.path.join(
#     r"D:\Dam_EBR_results\raw", run, 
#     r"results_simulations\base\_postprocess\_netcdf\watertable_elevation.nc"), 
#                       coords = coords_, epsg_coords = epsg_coords_, 
#                       epsg_data = 2154)
# =============================================================================
# run = 'Cheze_Dam_5.6'
# cheze_56 = gc.time_series(input_file = os.path.join(
#     r"D:\Dam_EBR_results\raw", run, 
#     r"results_simulations\base\_postprocess\_netcdf\watertable_elevation.nc"), 
#                       coords = coords_, epsg_coords = epsg_coords_, 
#                       epsg_data = 2154)

# run = 'Cheze_Dam_5.7'
# cheze_57 = gc.time_series(input_file = os.path.join(
#     r"D:\Dam_EBR_results\raw", run, 
#     r"results_simulations\base\_postprocess\_netcdf\watertable_elevation.nc"), 
#                       coords = coords_, epsg_coords = epsg_coords_, 
#                       epsg_data = 2154)

for run in ['5.8', '5.9', '6.0']:
    name = f"Cheze_Dam_{run}"
    idx = int(run.replace('.', ''))
    
    ds_dict[idx] = gc.time_series(
        input_file = os.path.join(
            r"D:\Dam_EBR_results\raw", name, 
            r"results_simulations\base\_postprocess\_netcdf\watertable_elevation.nc"),
        coords = coords_, epsg_coords = epsg_coords_, 
        epsg_data = 2154)
    
    timeseries = pd.read_csv(os.path.join(r"D:\Dam_EBR_results\raw", name,
                                r"results_simulations\base\_postprocess\_timeseries",
                                "_simulated_timeseries.csv"),
                             sep = ";",
                             header = 0,
                             skiprows = 0,
                             index_col = 'date',
                             usecols = ['date', 'reservoir_cheze_level', 
                                        'reservoir_cheze_volume',
                                        'reservoir_cheze_area'],
                             parse_dates = True)
    
    levels_dict[idx] = timeseries[['reservoir_cheze_level']].copy()
    levels_dict[idx].rename(columns = {'reservoir_cheze_level' : 'val'}, inplace = True)
    levels_dict[idx]['time'] = levels_dict[idx].index
    volumes_dict[idx] = timeseries[['reservoir_cheze_volume']].copy()
    volumes_dict[idx].rename(columns = {'reservoir_cheze_volume' : 'val'}, inplace = True)
    volumes_dict[idx]['time'] = volumes_dict[idx].index
    areas_dict[idx] = timeseries[['reservoir_cheze_area']].copy()
    areas_dict[idx].rename(columns = {'reservoir_cheze_area' : 'val'}, inplace = True)
    areas_dict[idx]['time'] = areas_dict[idx].index
    
# =============================================================================
# # Convert levels into volumes:
# for t in cheze_19.time[1:]:
#     cheze_19.watertable_elevation.loc[dict(time = t)] = abaque_model[abaque_model.level < float(cheze_19.watertable_elevation.loc[dict(time = t)])].iloc[-1].volume
# 
# volume_19 = pd.read_csv(r"D:\Dam_EBR_results\raw\cheze_Dam_1.9\results_simulations\base\_postprocess\_timeseries\_simulated_timeseries.csv",
#                         sep = ";",
#                         index_col = 'date',
#                         usecols = ['date', 'reservoir_cheze_volume'],
#                         parse_dates = True)
# volume_19['time'] = volume_19.index
# volume_19['val'] = volume_19['reservoir_cheze_volume']
# =============================================================================


#%% VISUALIZATION
##%%% Echelle manuelle
_cmap_catalog = [
    [1.000, 0.500, 0.000, 0.9],  # 0. orange
    [0.980, 0.691, 0.168, 0.9],  # 1. orange-jaune (pour *.html)
    [0.973, 0.392, 0.420, 0.9],  # 2. orange-rose
    [0.847, 0.000, 0.035, 0.9],  # 3. rouge royal
    [0.471, 0.000, 0.118, 0.9],  # 4. blackred
    [1.000, 0.557, 0.827, 0.9],  # 5. rose bonbon
    [0.949, 0.000, 0.784, 0.9],  # 6. fuschia
    [0.655, 0.204, 0.886, 0.9],  # 7. pourpre
    [0.404, 0.059, 0.902, 0.9],  # 8. violet fugace
    [0.000, 0.000, 0.470, 0.9],  # 9. bleu marine - noir
    [0.000, 0.318, 0.910, 0.9],  # 10. bleu
    [0.000, 0.707, 0.973, 0.9],  # 11. bleu ciel
    [0.000, 0.757, 0.757, 0.9],  # 12. bleu-vert émeraude
    [0.625, 0.777, 0.027, 0.9],  # 13. vert
    [0.824, 0.867, 0.141, 0.9],  # 14. vert-jaune (ou l'inverse)
    [1.000, 0.784, 0.059, 0.9],  # 15. jaune-orangé
    [1.000, 0.941, 0.059, 0.9],  # 16. jaune
    [0, 0, 0, 1],                # 17. noir
    [0.37, 0.37, 0.37, 1],       # 18. gris sombrero
    [0.70, 0.70, 0.70, 1],       # 19. gris clairero
    ]
#% Color map par paires
color_map = np.array(_cmap_catalog)[[17, 3, 13, 1, 10, 7, 16, 8, 13, 2, 10, 8, 3, 11, 10, 1, 14, 13, 13, 14, 12, 9, 11, 8, 3, 4, 12, 13, 0], :]

metric = 'volume' # user-defined

[fig1, ax1, figweb] = cwp.plot_time_series(dataframes = [results[metric]['data'],
                                                         # results[metric][58], # cheze_58
                                                          results[metric][59], # cheze_59
                                                         results[metric][60],
                                                         ],
                                           labels = ['mesures',
                                                     # "run 5.8 daily (thick = 30m | poro = 0.1% | K = 3.4e-5 m/s)",
                                                     "run 5.9 weekly (thick = 30m | poro = 0.1% | K = 3.4e-5 m/s)",
                                                     "run 60 weekly (thick = 45m | poro = 0.1% | K = 8e-5 m/s)",
                                                     ],
                                           
                                           color_map = color_map,
                                           )

##%%% MISE EN FORME *.html (figweb)   
if metric == 'level':
    ylabel = 'elevation [m]'
elif metric == 'volume':
    ylabel = 'volume [m3]'
    
title = "Pré-calibration modèle physique"

figweb.update_layout(#font_family = 'Open Sans',
                   title = {'font': {'size': 20},
                            'text': title,
                            'xanchor': 'center',
                            'x': 0.5,
                            },
                   # annotations = {'xanchor': 'middle',
                   #                'yanchor': 'top',
                   #                'size': 20,
                   #                'text': add_title + "\nK = 5e-6 m/s   Poro = 0.1%   e = 25 m"},
                   xaxis = {'title': {'font': {'size': 16},
                                      'text': 'time [d]'},
                            # 'range': dates_lim,
                            },
                   yaxis = {'title': {'font': {'size': 16},
                                       'text': ylabel},
                                      # 'text': field_title + ' [m3/s]'},
                            'type': 'linear',
                            'range': [0, 25000000],#_ylim_figweb,
                            },
                   legend = {'title': {'text': 'Légende'},
                             'xanchor': 'right',
                             'y': 0.9,
                             'yanchor': 'top',
                             'bgcolor': 'rgba(255, 255, 255, 0.2)',
                             },
                   plot_bgcolor = "white",
                   # legend = {'groupclick': 'togglegroup'},
                   width = 1500,
                   height = 700,
                   )

##%%% Horizontal line
if metric == 'level':
    val_RN = 87.3 # [m]
elif metric == 'volume':
    val_RN = 14400000 # [m3]'
figweb.add_hline(y = val_RN, line_dash = "dot",
                 line_color = 'rgba(0, 0, 0, 0.50)', line_width = 0.5,
                 annotation_text = "limite retenue normale", # Annotation only in the first one
                 # annotation_position = "bottom right",
                 annotation_font_size = 11,
                 annotation_font_color = 'rgba(0, 0, 0, 0.50)',
                 annotation_textangle = 0,
                 )



figweb.write_html(os.path.join(r"D:\2- Postdoc\2- Travaux\8_Dam_EBR\results\processed",
                               '_'.join([metric, 
                                         datetime.datetime.now().strftime("%Y-%m-%d_%Hh%M"),
                                         ]) + '.html'
                               )
                  )