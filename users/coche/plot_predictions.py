# -*- coding: utf-8 -*-
"""
Created on Mon Feb 12 01:46:55 2024

@author: Alexandre Coche

Tools to visualize lake/reservoir simulation results.
This script is not a function nor a class. For now it is designed to be run 
inside Spyder, section by section.
"""

#%% IMPORTS
from pywtraj import (
    geohydroconvert as ghc,
    ncplot as nc,
    cmapgenerator as cmg)
import numpy as np
import os
import datetime
import pandas as pd
from src.tools import folder_root

#%% LOAD DATA & PARAMETERS
# ---- Language [USER CHOICE]
### User-defined language:
language = 'fr'

language_dict = {"en": 0,
                 "fr": 1,}
lang = language_dict[language]

# ---- Graphical plot size
# Two formats are defined here: wide and paper
wide = (1500, 700) # (width, height)
paper = (1000, 550)
plot_size = paper

# ---- Coordinates [USER CHOICE]
# (Coordinates where results will be extracted)
### User-defined coordinates
epsg_coords_ = 2154

coords_outlet = (330975, 6780825) # reservoir outlet (within the reservoir)
coords_overflow = (331050, 6780900) # 1st cell downstream the reservoir
# coords_ = (331125, 6780975) # 2nd cell downstream the reservoir

# Alternatively, coords can also be a filepath to a mask. In that case, the
# mean value over this mask will be retrieved.

# ---- Load input data [USER CHOICE]
# res_path = r"D:\Dam_EBR_results\raw"
# res_path = r"D:\HyMoPy\results\raw2"
res_path = folder_root.root_folder_results()
data_path = os.path.join(res_path, "LakeRes")

abaque = pd.read_csv(os.path.join(data_path, r"Reservoir\Abaque\abaque_cheze_2020.csv"),
                     # r"D:\2- Postdoc\2- Travaux\1- Veille\1- Biblio locale\14- Barrage\bathymetrie Cheze\abaque_cheze_2020.csv",
                     sep = "\t",
                     header = 0,
                     names = ['level', 'volume'],
                     )

abaque_model = pd.read_csv(r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\6- Lacs et reservoirs\Cheze\bathymetry\reflexion bathymetrie\modeled_abaque_1m_v2extended.csv",
                           sep = "\t",
                           header = 0,
                           names = ['level', 'volume'],
                           )

dam_data_path = os.path.join(r"D:\2- Postdoc\2- Travaux\1- Veille", 
                             r"1- Biblio locale\14- Barrage",
                             "Documents_travail_Ronan\dam_data",
                             r"dam_cheze_volume_raw_2000-2022.csv")

data = pd.read_csv(dam_data_path,
                   sep = ";",
                   header = 0,
                   skiprows = 0,
                   index_col = 'time',
                   # usecols = ['time', 'cheze'],
                   parse_dates = True)

# ---- Raffinage des flux d'entrée récents à partir des données journalières
print("   . Raffinage des flux d'entrée avec les données journalières :")

Flux_Cheze_xls_folder = os.path.join(data_path, "Reservoir",
                                     "Donnees journalieres EBR", "Flux")

for path, folders, files in os.walk(Flux_Cheze_xls_folder):
    if len(files) > 0:
        print(f"        mise-à-jour {os.path.split(path)[-1]}")
        for f in files:
            if (f[0] != '~') & (f[-8:-5].casefold() != 'old'):
                if f[-11:-5] in ['1_2020', '2_2020', '3_2020',
                                 '4_2020', '5_2020']: # ancien format
                    data_refined = pd.read_excel(
                        os.path.join(path, f),
                        # sheet_name = "Histos",
                        # index_col = 0,
                        skiprows = 6, # [5],
                        header = None, #[3, 4],
                        usecols = [1, 7, 9, 11, 13, 14],
                        names = ['time', 'canut', 'cheze', 'resti', 'meu', 'usine'],
                        index_col = 0,
                        skipfooter = 4,
                        parse_dates = False,
                        # date_format = '%d/%m/%Y',
                        na_values = ['No Data'],
                        )
                    data_refined['radar'] = data_refined['cheze']
                else:
                    data_refined = pd.read_excel(
                        os.path.join(path, f),
                        # sheet_name = "Histos",
                        # index_col = 0,
                        skiprows = 6, # [5],
                        header = None, #[3, 4],
                        usecols = [1, 7, 9, 10, 12, 14, 15],
                        names = ['time', 'canut', 'radar', 'cheze', 'resti', 'meu', 'usine'],
                        index_col = 0,
                        skipfooter = 4,
                        parse_dates = False,
                        # date_format = '%d/%m/%Y',
                        na_values = ['No Data'],
                        )
                data_refined = data_refined[data_refined.index.notna()] # remove the rows with no date
                # data_refined.dropna(axis = 0, how = 'all', inplace = True) # remove the last rows if empty
                data_refined.index = pd.to_datetime(data_refined.index, format = '%d/%m/%Y')
                # Use radar values to fill in missing piezo values:
                data_refined.loc[data_refined.cheze.isna(), 'cheze'] = data_refined.radar[data_refined.cheze.isna()] 
                data_refined = data_refined.loc[:, data_refined.columns != 'radar']
                data_refined.interpolate(method = 'time', inplace = True)
                
                # data_refined = data_refined.resample(freq_input).agg({var:rules[var] for var in data_refined.columns})

                # Conversion des niveaux en volumes
                # ---------------------------------
                for t in data_refined.index:
                    if not abaque[abaque.level <= data_refined.cheze.loc[t].item()].empty:
                        data_refined.loc[t, 'cheze'] = abaque[abaque.level <= data_refined.cheze.loc[t].item()].iloc[-1].volume
                    else:
                        if data_refined.loc[t, 'cheze'].item() > abaque.level.max():
                            slope = (abaque.level.iloc[-1] - abaque.level.iloc[-2]) / (abaque.volume.iloc[-1] - abaque.volume.iloc[-2])
                            add_volume = abaque.volume.iloc[-1] + (data_refined.cheze.loc[t].item() - abaque.level.iloc[-1])/slope
                            abaque_interp = abaque.append({'volume':add_volume, 'level':data_refined.cheze.loc[t].item()}, 
                                                          ignore_index = True)
                        elif data_refined.loc[t, 'cheze'].item() < abaque.level.min():
                            slope = (abaque.level.iloc[1] - abaque.level.iloc[0]) / (abaque.volume.iloc[1] - abaque.volume.iloc[0])
                            add_volume = abaque.volume.iloc[0] + (data_refined.cheze.loc[t].item() - abaque.level.iloc[0])/slope
                            abaque_interp = pd.DataFrame(data_refined = {'volume':add_volume, 'level':data_refined.cheze.loc[t].item()}, index = [0]).append(abaque, ignore_index = True)
                        data_refined.loc[t, 'cheze'] = abaque_interp[abaque_interp.level <= data_refined.cheze.loc[t].item()].iloc[-1].volume

                
                data = data.reindex(index = data.index.union(data_refined.index))
                for col in ['cheze', 'resti', 'meu', 'canut', 'usine']:
                    # data[col].update(data_refined[col])
                # data[['cheze', 'resti', 'meu', 'usine']].update(data_refined)
                    data[col] = data[col].combine_first(data_refined[col])


# ---- Initialize the results container
levels_dict = dict()
volumes_dict = dict()
areas_dict = dict()
leakage_down_dict = dict()
leakage_up_dict = dict()
leakage_dict = dict()
accumulation_dict = dict()
downstream_dict = dict()

df_dict = dict() # dict of datasets
ts_dict = dict() # dict of timeseries

results = {'volume': volumes_dict,
           'level': levels_dict,
           'area': areas_dict,
           'leakage_down': leakage_down_dict,
           'leakage_up': leakage_up_dict,
           'leakage': leakage_dict,
           'accumulation': accumulation_dict,
           'downstream': downstream_dict,
           }


# ---- Fill the results with the input data
# Volumes are taken from the 'cheze' column
volumes_dict['data'] = data[['cheze']].copy()

# The levels are converted from the volumes and the abac
levels_dict['data'] = volumes_dict['data'].copy()
for t in levels_dict['data'].index[0:-1]:
    levels_dict['data'].loc[t] = abaque[abaque.volume < levels_dict['data'].loc[t].values[0]].iloc[-1].level

# Convert values (monthly sums) into daily rates 
days_in_month = pd.DataFrame( 
    index = data.index,
    data = data.index.days_in_month)
days_in_month.rename(columns = {'time':'n_days'}, inplace = True)

# data = data.div(days_in_month.n_days, axis="index") # [m3/j]
sum_col = data.columns != 'cheze'
data.loc[:, sum_col] = data.loc[:, sum_col].divide(
    days_in_month.n_days, axis="index") # [m3/j]

#%% LOAD RESULTS [USER CHOICE]
run = 'barrage_Cheze_SFR_LAK_2024-11-02'

# List of all scenarios (historical and predictive)
results_sim_folder = os.path.join(res_path, run, r"results_simulations")
scenario_list = [
    folder for folder in os.listdir(results_sim_folder)
    if (os.path.isdir(os.path.join(results_sim_folder, folder))) & (folder != '_figures')]

# Safeguard
if 'historique' not in scenario_list:
    print("Err: 'historique' scenario is missing")

# List of predictive scenarios
scenario_p_list = [f for f in scenario_list if f != 'historique']

# List of climatic experiences for each scenario
predic_dict = dict()
predic_dict['historique'] = ['sim2']
for scenario in scenario_p_list:
    predic_dict[scenario] = [
        folder for folder in os.listdir(os.path.join(results_sim_folder, scenario))
        ]

# Load data
scenario = 'historique'
for scenario in scenario_list:
    # Initializations
    df_dict[scenario] = dict()
    ts_dict[scenario] = dict()
    accumulation_dict[scenario] = dict()
    levels_dict[scenario] = dict()
    volumes_dict[scenario] = dict()
    areas_dict[scenario] = dict()
    leakage_down_dict[scenario] = dict()
    leakage_up_dict[scenario] = dict()
    leakage_dict[scenario] = dict()
    downstream_dict[scenario] = dict()
    
    for exp in predic_dict[scenario]:
        if scenario == 'historique':
            res_subpath = os.path.join(results_sim_folder, scenario)
        else:
            res_subpath = os.path.join(results_sim_folder, scenario, exp)
    
        # ---- Load complete files
        # The results can be loaded from 2 sources:
        try:
             # 1. The NetCDF watertable file:
            df_dict[scenario][exp] = dict()
            # Watertable
            df_dict[scenario][exp]['level'] = ghc.time_series(
                input_file = os.path.join(
                    res_subpath, 
                    r"_postprocess\_netcdf\watertable_elevation.nc"),
                coords = coords_outlet, epsg_coords = epsg_coords_, 
                epsg_data = 2154)
            # Overflow & returnflow
            df_dict[scenario][exp]['downstream'] = ghc.time_series(
                input_file = os.path.join(
                    res_subpath, 
                    r"_postprocess\_netcdf\accumulation_flux.nc"),
                coords = coords_overflow, epsg_coords = epsg_coords_, 
                epsg_data = 2154)    
        
             # 2. The .csv timeseries tables:
             # (in that case, the coordinates are not used)
            ts_dict[scenario][exp] = pd.read_csv(os.path.join(res_subpath,
                                        r"_postprocess\_timeseries",
                                        "_simulated_timeseries.csv"),
                                     sep = ";",
                                     header = 0,
                                     skiprows = 0,
                                     index_col = 'date',
                                     parse_dates = True)
            
            # ---- Extract general results
            accumulation_dict[scenario][exp] = ts_dict[scenario][exp][['accumulation_flux']].copy()
        
            
            # ---- Extract lake/reservoir results
# =============================================================================
#             levels_dict[scenario][exp] = ts_dict[scenario][exp][['reservoir_cheze_level']].copy()
#             levels_dict[scenario][exp].rename(columns = {'reservoir_cheze_level' : 'val'}, inplace = True)
#             levels_dict[scenario][exp]['time'] = levels_dict[scenario][exp].index
# =============================================================================
            # levels_dict[scenario][exp] = df_dict[scenario][exp].drop(['x', 'y', 'spatial_ref']).to_dataframe()
            levels_dict[scenario][exp] = df_dict[scenario][exp]['level'][['watertable_elevation']]
            volumes_dict[scenario][exp] = ts_dict[scenario][exp][['reservoir_cheze_volume']].copy()
            areas_dict[scenario][exp] = ts_dict[scenario][exp][['reservoir_cheze_area']].copy()
            
            # ---- Extract lake/reservoir flux results
            leakage_down_dict[scenario][exp] = -ts_dict[scenario][exp][['reservoir_cheze_lake_leakage_downwards']].copy()
            leakage_up_dict[scenario][exp] = ts_dict[scenario][exp][['reservoir_cheze_lake_leakage_upwards']].copy()
            leakage_dict[scenario][exp] = -ts_dict[scenario][exp][['reservoir_cheze_lake_leakage']].copy()
# =============================================================================
#             leakage_dict[scenario][exp] = -df_dict[scenario][exp]['reservoir_cheze_lake_leakage'].drop(['x', 'y', 'spatial_ref']).to_dataframe()
#             leakage_dict[scenario][exp].rename(columns = {'lake_leakage' : 'val'}, inplace = True)
#             leakage_dict[scenario][exp]['time'] = accumulation_dict[scenario][exp].index
# =============================================================================
            # downstream_dict[scenario][exp] = -df_dict[scenario][exp]['downstream'].drop(['x', 'y', 'spatial_ref']).to_dataframe()
            downstream_dict[scenario][exp] = -df_dict[scenario][exp]['downstream'][['accumulation_flux']]
        
# =============================================================================
#         # Convert levels into volumes:
#         for t in cheze_19.time[1:]:
#             cheze_19.watertable_elevation.loc[dict(time = t)] = abaque_model[abaque_model.level < float(cheze_19.watertable_elevation.loc[dict(time = t)])].iloc[-1].volume
#         
#         volume_19 = pd.read_csv(r"D:\Dam_EBR_results\raw\cheze_Dam_1.9\results_simulations\base\_postprocess\_timeseries\_simulated_timeseries.csv",
#                                 sep = ";",
#                                 index_col = 'date',
#                                 usecols = ['date', 'reservoir_cheze_volume'],
#                                 parse_dates = True)
#         volume_19['time'] = volume_19.index
#         volume_19['val'] = volume_19['reservoir_cheze_volume']
# =============================================================================
            
# =============================================================================
#             # Convert levels into volumes (overwrite previous values!):
#             for t in volumes_dict[scenario][exp].index[1:]:
#                 volumes_dict[scenario][exp].loc[t, 'val'] = abaque_model[abaque_model.level < float(levels_dict[scenario][exp].val[t])].iloc[-1].volume
# =============================================================================
                
# =============================================================================
#             # Convert volumes into levels (overwrite previous values!):
#             for t in levels_dict[scenario][exp].index[1:]:
#                 levels_dict[scenario][exp].loc[t, 'val'] = abaque_model[abaque_model.volume < float(volumes_dict[scenario][exp].val[t])].iloc[-1].level
# =============================================================================
        
        except:
            print(f"Err: the simulation {scenario}:{exp} does not contains post-processed results")


#%% VISU Vol/Lvl/Area
# ---- Colorscale [USER CHOICE]
color_map_fill = np.vstack(cmg.discrete('ibm', alpha = 1,
                                        black = False, alternate = False),
# =============================================================================
#                       cmg.discrete('wong', alpha = 1, 
#                                         black = False, alternate = False),
#                       cmg.discrete('wong', alpha = 1, 
#                                         black = False, alternate = False)
# =============================================================================
                      )
color_map_line = color_map_fill.copy()
color_map_line[:, -1] = 0
# =============================================================================
# color_map = color_map[[0, 2,3, 4,5, 6,7]]
# =============================================================================

# ---- Metric [USER CHOICE]
metric = 'level' ### user-defined (level | volume | area | accumulation)

# ---- Determine min and max for each scenario
merge_res = dict()
graph_res = dict() # results formated for the graphics
for scenario in scenario_p_list:
    predic_list = list(results[metric][scenario].keys())
    merge_res[scenario] = results[metric][scenario][predic_list[0]].copy()
    for k in range(1, len(predic_list)):
        predic = predic_list[k]
        results[metric][scenario][predic] = results[metric][scenario][predic].rename(
            columns = {results[metric][scenario][predic].columns.item(): predic})
        merge_res[scenario] = merge_res[scenario].merge(results[metric][scenario][predic], 
                                                        left_index = True, 
                                                        right_index = True,
                                                        how = 'outer')
    # Extract min and max
    min_res = merge_res[scenario].min(axis = 1)
    min_res = min_res.to_frame('min')
    max_res = merge_res[scenario].max(axis = 1)
    max_res = max_res.to_frame('max')
    min_res = min_res.merge(max_res, 
                            left_index = True,
                            right_index = True)
    graph_res[scenario] = min_res


# ---- Figures
figweb = None
# Historique
[fig1, ax1, figweb] = nc.plot_time_series(figweb = figweb,
                                           data = [results[metric]['historique']['sim2']],
                                           fill = None,
                                           labels = ['Historique'],
                                           linecolors = np.array([[0.7, 0.7, 0.7, 1]]),
                                           lwidths = [3],
                                           lstyle = ['-'],
                                           # legendgrouptitle_text = year_labels[p],
                                           showlegend = True)
# Predictions
for p in range(0, len(scenario_p_list)):
    scenario = scenario_p_list[p]
    [fig1, ax1, figweb] = nc.plot_time_series(figweb = figweb,
                                               data = [graph_res[scenario]['min']],
                                               fill = None,
                                               labels = [scenario],
                                               linecolors = color_map_line[[p]],
                                               # fillcolor = color_map2[[p]],
                                               lwidths = [1.5],
                                               lstyle = ['-'],
                                               legendgroup = p,
                                               # legendgrouptitle_text = year_labels[p],
                                               showlegend = False)
    [fig1, ax1, figweb] = nc.plot_time_series(figweb = figweb,
                                               data = [graph_res[scenario]['max']],
                                               fill = 'tonexty',
                                               labels = [scenario],
                                               fillcolors = color_map_fill[[p]],
                                               linecolors = color_map_line[[p]],
                                               # fillcolor = color_map2[[p]],
                                               lwidths = [1.5],
                                               lstyle = ['-'],
                                               legendgroup = p,
                                               # legendgrouptitle_text = year_labels[p],
                                               showlegend = True)
# Data
[fig1, ax1, figweb] = nc.plot_time_series(figweb = figweb,
                                           data = [results[metric]['data'][:-1]],
                                           labels = ['data'],
                                           linecolors = np.array([[0.0, 0.0, 0.0, 1]]),
                                           # fillcolor = color_map2[[p]],
                                           lwidths = [1],
                                           lstyle = ['dotted'],
                                           showlegend = True)



# ---- MISE EN FORME *.html (figweb)   
if metric == 'level':
    ylabel = ['Elevation [m]', 'Altitude [m]']
    ylim = [80, 95]
elif metric == 'volume':
    ylabel = ['Volume [m<sup>3</sup>]', 'Volume [m<sup>3</sup>]']
    ylim = [0, 25000000]
elif metric == 'accumulation':
    ylabel = ['Accumulation flux [m<sup>3</sup>/d]', 
              "Flux d'accumulation [m<sup>3</sup>/d]"]
    ylim = [0, 120000]
elif metric == 'area':
    ylabel = ['Reservoir extent',
              'Etendue du réservoir']
    ylim = [0, 2e6]

# ---- Dates [USER CHOICE]
# dates_lim = ['2000-01-01', '2024-02-23']
dates_lim = [results[metric]['historique']['sim2'].index.min(),
             results[metric][scenario][predic].index.max()]

# ---- Title [USER CHOICE]
title = f"Prévisions à date du {run[-10:]}"

# ---- Generation of the figure
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
                                      'text': ['Time [d]', 'Temps [j]'][lang]},
                            'range': dates_lim,
                            
                            },
                   yaxis = {'title': {'font': {'size': 16},
                                       'text': ylabel[lang]},
                                      # 'text': field_title + ' [m3/s]'},
                            'type': 'linear',
                            'range': ylim,#_ylim_figweb,
                            },
                   legend = {'title': {'text': 'Légende'},
                             'xanchor': 'right',
                             'y': 1.1,
                             'yanchor': 'top',
                             'bgcolor': 'rgba(255, 255, 255, 0.2)',
                             },
                   plot_bgcolor = "white",
                   # legend = {'groupclick': 'togglegroup'},
                   width = plot_size[0], # paper[0], # wide[0],
                   height = plot_size[1], # paper[1], # wide[1],
                   )

##%%% Horizontal line
if metric == 'level':
    val_RN = 87.3 # [m]
elif metric == 'volume':
    val_RN = 14400000 # [m3]'
elif metric == 'area':
    val_RN = 0 # to define

if metric in ['level', 'volume', 'area']:
    figweb.add_hline(y = val_RN, line_dash = "dot",
                     line_color = 'rgba(0, 0, 0, 0.50)', line_width = 0.5,
                     annotation_text = ["maximum level", "limite retenue normale"][lang], # Annotation only in the first one
                     # annotation_position = "bottom right",
                     annotation_font_size = 11,
                     annotation_font_color = 'rgba(0, 0, 0, 0.50)',
                     annotation_textangle = 0,
                     )

# ---- Export the figure [USER CHOICE]
figweb.write_html(os.path.join(os.path.split(res_path)[0], "processed",
                               '_'.join([metric, 
                                         datetime.datetime.now().strftime("%Y-%m-%d_%Hh%M"),
                                         ]) + '.html'
                               )
                  )

figweb.write_image(os.path.join(os.path.split(res_path)[0], "processed",
                               '_'.join([metric, 
                                         datetime.datetime.now().strftime("%Y-%m-%d_%Hh%M"),
                                         ]) + '.png'
                               )
                  )
