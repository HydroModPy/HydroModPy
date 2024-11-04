# -*- coding: utf-8 -*-
"""
Created on Fri Apr  5 18:08:57 2024

Based on the work of Ronan Abhervé and Loic Duffar (https://github.com/loicduffar)

@author: Alexandre Coche
"""

"""
WORKFLOW:
 import SIM2_tools as smt
 sim_folder = r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\8- Meteo\Surfex\SIM2"
    
 <1> Pour traiter les données par paquets, adapter la variable batch_var au 
 début de la fonction to_netcdf()
 <2> smt.folder_to_netcdf(os.path.join(sim_folder, "csv"))
 <3> smt.merge_folder(os.path.join(sim_folder, "netcdf"))
 <4> Supprimer si besoin les fichiers dans \netcdf\
 <5> smt.compress_folder(os.path.join(sim_folder, "merged"))
 <6> smt.clip_folder(os.path.join(sim_folder, "compressed"), 
                     os.path.join(sim_folder, "Bretagne_rectangle.shp"))
 <7> Déplacer les clipped dans \Bretagne\
 <8> smt.clip_folder(os.path.join(sim_folder, "merged"), 
                     os.path.join(sim_folder, "EBR_rectangle.shp")
 <9> Déplacer les clipped dans \EBR\
<10> Déplacer les compressed dans done
<11> Déplacer les merged sur le DDext
"""


#%% Imports
import os
import re
import datetime
import pandas as pd
import numpy as np
import xarray as xr
xr.set_options(keep_attrs = True)
import rioxarray as rio #Not necessary, the rio module from xarray is enough
import geopandas as gpd
from shapely.geometry import mapping
import geoconvert as gc
import plotly.graph_objects as go
import plotly.offline as offline
from PIL import Image


#%% Convert to NetCDF
def to_netcdf(csv_file_path):
    start_time = datetime.datetime.now()
    print("Start time: ", start_time.strftime("%Y-%m-%d %H:%M"))
    
    root_folder = os.path.split(os.path.split(csv_file_path)[0])[0]
# =============================================================================
#     coords_filepath = os.path.join(
#         root_folder, 'coordonnees_grille_safran_lambert-2-etendu.csv')
# =============================================================================
    
    # Needed columns
    usecols = ['LAMBX', 'LAMBY', 'DATE']

    # Units and long names (from liste_parametres.odt https://www.data.gouv.fr/fr/datasets/r/d1ffaf5e-7d15-4fb5-a34c-f76aaf417b46)
    units_by_var = {
                 'PRENEI_Q': ['mm', 'Précipitations solides (cumul quotidien 06-06 UTC)'], 
                 'PRELIQ_Q': ['mm', 'Précipitations liquides (cumul quotidien 06-06 UTC)'], 
                 'T_Q': ['°C','Température (moyenne quotidienne)'], 
                 'FF_Q': ['m/s', 'Vitesse du vent (moyenne quotidienne)'], 
                 'Q_Q': ['g/kg','Humidité spécifique (moyenne quotidienne)'], 
                 'DLI_Q': ['J/cm2', 'Rayonnement atmosphérique (cumul quotidien)'],
                 'SSI_Q': ['J/cm2', 'Rayonnement visible (cumul quotidien)'], 
                 'HU_Q': ['%', 'Humidité relative (moyenne quotidienne)'], 
                 'EVAP_Q': ['mm', 'Evapotranspiration réelle (cumul quotidien 06-06 UTC)'], 
                 'ETP_Q': ['mm', 'Evapotranspiration potentielle (formule de Penman-Monteith)'], 
                 'PE_Q': ['mm', 'Pluies efficaces (cumul quotidien)'], 
                 'SWI_Q': ['%', "Indice d'humidité des sols (moyenne quotidienne 06-06 UTC)"],
                 'DRAINC_Q': ['mm', 'Drainage (cumul quotidien 06-06 UTC)'], 
                 'RUNC_Q': ['mm', 'Ruissellement (cumul quotidien 06-06 UTC)'], 
                 'RESR_NEIGE_Q': ['mm', 'Equivalent en eau du manteau neigeux (moyenne quotidienne 06-06 UTC)'], 
                 'RESR_NEIGE6_Q': ['mm', 'Equivalent en eau du manteau neigeux à 06 UTC'], 
                 'HTEURNEIGE_Q': ['m', 'Epaisseur du manteau neigeux (moyenne quotidienne 06-06 UTC)'], 
                 'HTEURNEIGE6_Q': ['m', 'Epaisseur du manteau à 06 UTC'], 
                 'HTEURNEIGEX_Q': ['m', 'Epaisseur du manteau neigeux maximum au cours de la journée'], 
                 'SNOW_FRAC_Q': ['%', 'Fraction de maille recouverte par la neige (moyenne quotidienne 06-06 UTC)'], 
                 'ECOULEMENT_Q': ['mm', 'Ecoulement à la base du manteau neigeux'], 
                 'WG_RACINE_Q': ['mm','Contenu en eau liquide dans la couche racinaire à 06 UTC'], 
                 'WGI_RACINE_Q': ['mm', 'Contenu en eau gelée dans la couche de racinaire à 06 UTC'], 
                 'TINF_H_Q': ['°C', 'Température minimale des 24 températures horaires'], 
                 'TSUP_H_Q': ['°C', 'Température maximale des 24 températures horaires'],
                 'PRETOT_Q': ['mm', 'Précipitations totales (cumul quotidien 06-06 UTC)'], 
                 }
    # NB: Cumulated values (day 1) are summed from 06:00 UTC (day 1) to 06:00 UTC (day 2)
    # Therefore, days correspond to Central Standard Time days.
    
    #%%% BATCH (User-defined)
    #########################
    # Process all variables at once:
    # batch_var = list(units_by_var)[0:-1]
    
    # Process by batch:
    batch_var = list(units_by_var)[0:4]
    # batch_var = list(units_by_var)[4:8]
    # batch_var = list(units_by_var)[8:12]
    # batch_var = list(units_by_var)[12:16]
    # batch_var = list(units_by_var)[16:20]
    # batch_var = list(units_by_var)[20:-1] # the last variable (Precip) is used-defined 
    
    #%%% Loading
    print("Loading...")
    sub_time = datetime.datetime.now()
    print("   (Can take > 1 min per parameter for a whole decade)")
    
    df = pd.read_csv(csv_file_path, sep=';', 
                     usecols=usecols + batch_var,
                     header=0, decimal='.',
                     parse_dates=['DATE'],
                     # date_format='%Y%m%d', # Not available before pandas 2.0.0
                     )
    
    now = datetime.datetime.now()
    print("   Loading time:", now - sub_time)
    
    #%%% Formatting
    print("\nFormatting...")
    sub_time = datetime.datetime.now()
    
    df.rename(columns = {'LAMBX': 'x', 'LAMBY': 'y', 'DATE': 'time'}, inplace = True)
    df[['x', 'y']] = df[['x', 'y']]*100 # convert hm to m
    df.set_index(['time', 'y', 'x'], inplace = True)
    
    # Add new quantities if needed
    if ('PRENEI_Q' in df.columns) & ('PRELIQ_Q' in df.columns):
        df['PRETOT_Q'] = df['PRENEI_Q'] + df['PRELIQ_Q']
        print("   New column added: PRETOT_Q = PRENEI_Q + PRELIQ_Q")
        
    ds = df.to_xarray()
    # Continuous axis
    ds = ds.reindex(x = range(ds.x.min().values, ds.x.max().values + 8000, 8000))
    ds = ds.reindex(y = range(ds.y.min().values, ds.y.max().values + 8000, 8000))
    # Include CRS
    ds.rio.write_crs(27572, inplace = True)
    # Standard attributes
    ds.x.attrs = {'standard_name': 'projection_x_coordinate',
                  'long_name': 'x coordinate of projection',
                  'units': 'Meter'}
    ds.y.attrs = {'standard_name': 'projection_y_coordinate',
                  'long_name': 'y coordinate of projection',
                  'units': 'Meter'}
    
    now = datetime.datetime.now()
    print("   Formatting time:", now - sub_time)
    
    #%%% Export
    print("\nExporting...")
    sub_time = datetime.datetime.now()
    
    if not os.path.exists(os.path.join(root_folder, "netcdf")):
        os.mkdir(os.path.join(root_folder, "netcdf"))
    
    for var in list(ds.data_vars): # batch_var: 
        # Include metadata
        ds[var].attrs = {'standard_name': var,
                         'long_name': units_by_var[var][1],
                         'units': units_by_var[var][0]}
        
        ds_var = ds[[var]]
        
        csv_name = os.path.splitext(os.path.split(csv_file_path)[-1])[0].replace('QUOT_', '')
        
        ds_var.to_netcdf(os.path.join(root_folder, 'netcdf', '_'.join([var, csv_name]) + '.nc'))     
        print(f"   {var} exported")
    
    now = datetime.datetime.now()
    print("   Formatting time:", now - sub_time)
        
    # afficher la durée d'éxécution
    now = datetime.datetime.now()
    print("\nEnd time:", now.strftime("%Y-%m-%d %H:%M"))
    print("Total time:", now - start_time)


#%% Convert whole folder to netcdf
def folder_to_netcdf(folder):
    """
    Parameters
    ----------
    folder : str
        Folder containing the .csv files.

    Returns
    -------
    None. Creates the .nc files in the folder 'netcdf'

    """
    
    filelist = [f for f in os.listdir(folder) 
                if (os.path.isfile(os.path.join(folder, f))) & (os.path.splitext(f)[-1] == '.csv')]
    
    for f in filelist:
        filename = os.path.splitext(f)[0]
        sim_pattern = re.compile('SIM2_')
        years = sim_pattern.split(filename)[-1]
        print(f"\n{'-'*len(years)}\n{years}\n{'-'*len(years)}")
        to_netcdf(os.path.join(folder, f))
    

#%% Merge
def merge(filelist):
    root_folder = os.path.split(os.path.split(filelist[0])[0])[0]
    
    print('\nMerging files...')
    
    with xr.open_dataset(
            filelist[0], decode_coords = 'all', decode_times = True) as ds_merged:
        ds_merged.load() # to unlock the resource
    print(f"   {os.path.split(filelist[0])[-1]}")
    
    encod = ds_merged[list(ds_merged.data_vars)[0]].encoding
    
    for f in filelist[1:]:
        with xr.open_dataset(
                f, decode_coords = 'all', decode_times = True) as ds:
            ds_merged = ds.combine_first(ds_merged)
        print(f"   {os.path.split(f)[-1]}")
    
    ds_merged = ds_merged.sortby('time')
    
    # Export
    ds_merged[list(ds_merged.data_vars)[0]].encoding = encod
    
    yearset = set()
    sim_pattern = re.compile('_SIM2_')
    year_pattern = re.compile('\d{4,8}')
    for f in filelist:
        filename = os.path.split(os.path.splitext(f)[0])[-1]
        var, years = sim_pattern.split(filename)
        yearset.update(year_pattern.findall(years))
    
    if not os.path.exists(os.path.join(root_folder, "merged")):
        os.mkdir(os.path.join(root_folder, "merged"))
    
    new_filepath = os.path.join(
        root_folder, 
        "merged", 
        '_'.join([var, 'SIM2', sorted(yearset)[0], sorted(yearset)[-1]]) + '.nc'
        )
    ds_merged.to_netcdf(new_filepath)
    

#%% Merge whole folder netcdf files
def merge_folder(folder):
    start_time = datetime.datetime.now()
    print("Start time: ", start_time.strftime("%Y-%m-%d %H:%M"))
    
    filelist = [f for f in os.listdir(folder) 
                if (os.path.isfile(os.path.join(folder, f))) & (os.path.splitext(f)[-1] == '.nc')]
    
    varlist = set()
    # Extract all variables
    for f in filelist:
        filename = os.path.splitext(f)[0]
        sim_pattern = re.compile('_SIM2_')
        var, _ = sim_pattern.split(filename)
        varlist.add(var)
        
    for v in varlist:
        print(f"\n{'-'*len(v)}\n{v}\n{'-'*len(v)}")
        
        sub_time = datetime.datetime.now()
        
        # Extract all years
        yearlist = []
        sim_pattern = re.compile('_SIM2_')
        for f in filelist:
            filename = os.path.splitext(f)[0]
            var, years = sim_pattern.split(filename)
            if var == v:
                yearlist.append(years)
            
        print(f"   {', '.join(yearlist)}")
        
        files_to_merge = [os.path.join(folder, v + '_SIM2_' + y + '.nc') for y in yearlist]
        merge(files_to_merge)
        now = datetime.datetime.now()
        print("\n   Merging time:", now - sub_time)
        
    # afficher la durée d'éxécution
    now = datetime.datetime.now()
    print("\nEnd time:", now.strftime("%Y-%m-%d %H:%M"))
    print("Total time:", now - start_time)
        
        

#%% Compress
def compress(filepath):    
    root_folder = os.path.split(os.path.split(filepath)[0])[0]
    
    with xr.open_dataset(filepath, decode_times = True,
                         decode_coords = 'all') as ds:
        ds.load() # to unlock the resource
        
    # Discretization compression (lossy):
    var = list(ds.data_vars)[0]
    bound_max = float(ds[var].max())
    bound_min = float(ds[var].min())
    if bound_min<0: bound_min = bound_min*1.1
    elif bound_min>0: bound_min = bound_min/1.1
    else: bound_min = bound_min - 0.01*bound_max
    scale_factor, add_offset = gc.compute_scale_and_offset(
        bound_min, bound_max, 16)
    ds[var].encoding['scale_factor'] = scale_factor
    ds[var].encoding['add_offset'] = add_offset
    ds[var].encoding['dtype'] = 'int16'
    ds[var].encoding['_FillValue'] = -32768
    print("   Compression x4 (lossy)")
    
    # Export
    if not os.path.exists(os.path.join(root_folder, "compressed")):
        os.mkdir(os.path.join(root_folder, "compressed"))
    
    filename = os.path.splitext(os.path.split(filepath)[-1])[0]
    new_filepath = os.path.join(
        root_folder, 'compressed', filename + '_comp.nc')
    ds.to_netcdf(new_filepath)
        
    
#%% Compress whole folder
def compress_folder(folder):
    start_time = datetime.datetime.now()
    print("Start time: ", start_time.strftime("%Y-%m-%d %H:%M"))
    
    filelist = [f for f in os.listdir(folder) 
                if (os.path.isfile(os.path.join(folder, f))) & (os.path.splitext(f)[-1] == '.nc')]
    
    print("\nCompressing...")
    
    i = 0
    for f in filelist:
        i += 1
        print(f"\n {'-'*len(f)}\n {f} ({i}/{len(filelist)})\n {'-'*len(f)}")
        sub_time = datetime.datetime.now()
        
        compress(os.path.join(folder, f))
        
        now = datetime.datetime.now()
        print("   Compression time:", now - sub_time)
        
    # afficher la durée d'éxécution
    now = datetime.datetime.now()
    print("\nEnd time:", now.strftime("%Y-%m-%d %H:%M"))
    print("Total time:", now - start_time)
    
    
#%% Clip
def clip(filepath, maskpath):
    root_folder = os.path.split(os.path.split(filepath)[0])[0]
    
    mask = gpd.read_file(maskpath)
    with xr.open_dataset(filepath, decode_times = True,
                         decode_coords = 'all') as ds:
        ds.load() # to unlock the resource
        
    clipped_ds = ds.rio.clip(mask.geometry.apply(mapping), 
                             mask.crs, all_touched = True)

    # Export
    if not os.path.exists(os.path.join(root_folder, "clipped")):
        os.mkdir(os.path.join(root_folder, "clipped"))
        
    filename = os.path.splitext(os.path.split(filepath)[-1])[0]
    new_filepath = os.path.join(
        root_folder, 'clipped', filename + '_clipped.nc')
    clipped_ds.to_netcdf(new_filepath)
    

#%% Clip whole folder
def clip_folder(folder, maskpath):
    start_time = datetime.datetime.now()
    print("Start time: ", start_time.strftime("%Y-%m-%d %H:%M"))
    
    filelist = [f for f in os.listdir(folder) 
                if (os.path.isfile(os.path.join(folder, f))) & (os.path.splitext(f)[-1] == '.nc')]
    
    maskname = os.path.splitext(os.path.split(maskpath)[-1])[0]
    
    print(f"\nClipping on {maskname}...")
    
    i = 0
    for f in filelist:
        i += 1
        print(f"\n {'-'*len(f)}\n {f} ({i}/{len(filelist)})\n {'-'*len(f)}")
        sub_time = datetime.datetime.now()
        
        clip(os.path.join(folder, f), maskpath)
        
        now = datetime.datetime.now()
        print("   Clipping time:", now - sub_time)
    
    # afficher la durée d'éxécution
    now = datetime.datetime.now()
    print("\nEnd time:", now.strftime("%Y-%m-%d %H:%M"))
    print("Total time:", now - start_time)
    

#%% Plot synthetic maps
def plot_map(var, *, file_folder = None, mode = "sum", timemode = 'annual'):
    """
    Generates interactive maps from SIM2 data (html).
    
    Example
    -------
    import SIM2_tools as smt
    smt.plot_map('PRETOT', mode = "sum", timemode = 'annual')

    Parameters
    ----------
    var : str
        SIM2 variables:
          'ETP' | 'EVAP' | 'PRELIQ' | 'PRENEI' | 'PRETOT' | 'DRAINC' | 'RUNC' | 
          'T' | 'TINF_H' | 'TSUP_H' | 'WG_RACINE' | 'WGI_RACINE' | 'SWI' | ...
    mode : str, optional
        'sum' | 'min' | 'max' | 'mean' | 'ratio' | 'ratio_precip'. The default is "sum".
    timemode : str, optional
        'annual' | 'ONDJFM' | 'AMJJAS. The default is 'annual'.

    Returns
    -------
    None. Creates the html maps.

    """
    
    start_time = datetime.datetime.now()
    # print("Start time: ", start_time.strftime("%Y-%m-%d %H:%M"))
    print("The generation of the interactive graphic file can take 1 min")
    
    #%%% Loading
    # Finding the most recent file
    if file_folder is None:
        file_folder = input("file folder: ")
    # Personal shortcut @Alexandre:
    if file_folder == '':
        file_folder = r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\8- Meteo\Surfex\SIM2\compressed"
        
    root_folder = os.path.split(file_folder)[0]
    
    var_pattern = re.compile(f"^{var}_Q")
    filelist = [f for f in os.listdir(file_folder) 
                if (os.path.isfile(os.path.join(file_folder, f))) \
                    & (os.path.splitext(f)[-1] == '.nc') \
                        & (len(var_pattern.findall(f)) > 0)]
    
    for f in filelist:
        print(f)
        # sim_pattern = re.compile('\d{4,6}')
        # years = int(sim_pattern.findall(f)[-1])
        file_suffix = 'Q_' + var_pattern.split(f)[1][1:]    
    print(f"   . File suffix: {file_suffix}")
    filename = f"{var}_{file_suffix}"
    filepath = os.path.join(file_folder, filename)
    
    # Loading as xarray.dataset
    with xr.open_dataset(
            filepath, decode_coords = 'all', decode_times = True) as ds:
        ds.load()
        
    main_var = list(ds.data_vars)[0]
    # xres = float(ds.x[1] - ds.x[0])
    # xres = ds.rio.transform()[0]
    # yres = float(ds.y[1] - ds.y[0])
    # yres = ds.rio.transform()[4]
    xres, yres = ds.rio.resolution()
    
    #%%% Initializations
    last_year = ds.time.max().dt.year.item()
    # The last incomplete hydrological year is not taken into account
    if timemode == 'ONDJFM':
        if ds.time.max() < pd.to_datetime(f"{last_year}-03-31", format = "%Y-%m-%d"):
            last_year = last_year-1
    else:
        if ds.time.max() < pd.to_datetime(f"{last_year}-09-30", format = "%Y-%m-%d"):
            last_year = last_year-1
        
    # Hydrological years (start and end years for each decade)
    annual_bins = [
        ((1958, 1959), (1969, 1970)),
        ((1965, 1966), (1974, 1975)),
        ((1970, 1971), (1979, 1980)),
        ((1975, 1976), (1984, 1985)),
        ((1980, 1981), (1989, 1990)),
        ((1985, 1986), (1994, 1995)),
        ((1990, 1991), (1999, 2000)),
        ((1995, 1996), (2004, 2005)),
        ((2000, 2001), (2009, 2010)),
        ((2005, 2006), (2014, 2015)),
        ((2010, 2011), (2019, 2020)),
        ((2015, 2016), (last_year - 1, last_year)),
        ]
    
    suf_title = []
    suf_slider = []
    
    suf_timemode = {
        'sum': {'annual': 'cumuls annuels',
                'ONDJFM': 'cumuls oct-mar',
                'AMJJAS': 'cumuls avr-sep'},
        'min': {'annual': 'minimums annuels',
                'ONDJFM': 'minimums oct-mar',
                'AMJJAS': 'minimums avr-sep'},
        'max': {'annual': 'maximums annuels',
                'ONDJFM': 'maximums oct-mar',
                'AMJJAS': 'maximums avr-sep'},
        'mean': {'annual': 'moyennes annuelles',
                'ONDJFM': 'moyennes oct-mar',
                'AMJJAS': 'moyennes avr-sep'},
        'ratio': {'annual': 'obsolète (cumuls annuels / cumuls annuels)',
                  'ONDJFM': 'cumuls oct-mar / cumuls annuels',
                  'AMJJAS': 'cumuls avr-sep / cumuls annuels'},
        'ratio_precip': {'annual': 'cumuls annuels / précipitations annuelles',
                         'ONDJFM': 'cumuls oct-mar / précipitations annuelles',
                         'AMJJAS': 'cumuls avr-sep / précipitations annuelles'},          
        }
    
    metadata_by_var = {
                 'PRENEI_Q': ['mm', 'Précipitations solides'], 
                 'PRELIQ_Q': ['mm', 'Précipitations liquides'], 
                 'T_Q': ['°C','Température moy. journalière'], 
                 'FF_Q': ['m/s', 'Vit. vent'], 
                 'Q_Q': ['g/kg','Humidité spécifique '], 
                 'DLI_Q': ['J/cm2', 'Rayonnement atmosphérique '],
                 'SSI_Q': ['J/cm2', 'Rayonnement visible '], 
                 'HU_Q': ['%', 'Humidité relative '], 
                 'EVAP_Q': ['mm', 'Evapotranspiration réelle'], 
                 'ETP_Q': ['mm', 'Evapotranspiration potentielle (Penman-Monteith)'], 
                 'PE_Q': ['mm', 'Pluies efficaces'], 
                 'SWI_Q': ['', 'Indice humidité des sols'],
                 'DRAINC_Q': ['mm', 'Recharge potentielle'], 
                 'RUNC_Q': ['mm', 'Ruissellement'], 
                 'RESR_NEIGE_Q': ['mm', 'Equivalent eau manteau neigeux'], 
                 'RESR_NEIGE6_Q': ['mm', 'Equivalent eau manteau neigeux'], 
                 'HTEURNEIGE_Q': ['m', 'Epaisseur manteau neigeux'], 
                 'HTEURNEIGE6_Q': ['m', 'Epaisseur du manteau neigeux'], 
                 'HTEURNEIGEX_Q': ['m', 'Epaisseur manteau neigeux maximum journalier'], 
                 'SNOW_FRAC_Q': ['%', 'Fraction maille recouverte par neige'], 
                 'ECOULEMENT_Q': ['mm', 'Ecoulement en base manteau neigeux'], 
                 'WG_RACINE_Q': ['mm','Contenu en eau liquide dans couche racinaire'], 
                 'WGI_RACINE_Q': ['mm', 'Contenu en eau gelée dans la couche de racinaire'], 
                 'TINF_H_Q': ['°C', 'Température min. journalière'], 
                 'TSUP_H_Q': ['°C', 'Température max. journalière'],
                 'PRETOT_Q': ['mm', 'Précipitations totales'], 
                 }
    
    fig = go.Figure()
    
    
    #%%% Units & colorscale
    dst_dir1 = 'valeurs'
    
    if mode in ["sum", "min", "max", "mean"]:
        unit = metadata_by_var[main_var][0]
        if mode == "sum":
            zmin = float(ds[main_var].groupby(
                ds.time.dt.year).sum(min_count = 1).min(dim = ['x', 'y', 'year']))
            zmax = float(ds[main_var].groupby(
                ds.time.dt.year).sum(min_count = 1).max(dim = ['x', 'y', 'year']))
        elif mode == "min":
            zmin = float(ds[main_var].groupby(
                ds.time.dt.year).min().min(dim = ['x', 'y', 'year']))
            zmax = float(ds[main_var].groupby(
                ds.time.dt.year).min().max(dim = ['x', 'y', 'year']))
        elif mode == "max":
            zmin = float(ds[main_var].groupby(
                ds.time.dt.year).max().min(dim = ['x', 'y', 'year']))
            zmax = float(ds[main_var].groupby(
                ds.time.dt.year).max().max(dim = ['x', 'y', 'year']))
        elif mode == "mean":
            zmin = float(ds[main_var].groupby(
                ds.time.dt.year).mean().min(dim = ['x', 'y', 'year']))
            zmax = float(ds[main_var].groupby(
                ds.time.dt.year).mean().max(dim = ['x', 'y', 'year']))
        
    elif mode == "ratio":
        unit = "%"
        zmin = 0
        zmax = 100
        dst_dir1 = 'pourcentages'
        
    elif mode == "ratio_precip":
        unit = "%"
        zmin = 0
        zmax = 100
        dst_dir1 = 'pourcentages precip'
        
    if var in ['T', 'TSUP_H', 'TINF_H']:
        colorscale = "Plasma_r"
    else:
        colorscale = "Viridis_r"
    
    #%%% Prepare data
    # ---- Exclude non-wanted months
    ds = ds[main_var].sel(
        time = slice(f"{str(annual_bins[0][0][0])}-10-01", f"{str(annual_bins[-1][1][1])}-09-30")
        )
    
    if timemode == 'ONDJFM':
        final_map = ds[(ds.time.dt.month <= 3) | (ds.time.dt.month >= 10)].copy()
    elif timemode == 'AMJJAS':
        final_map = ds[(ds.time.dt.month >= 4) & (ds.time.dt.month <= 9)].copy()
    elif timemode == 'annual':
        final_map = ds.copy()
        
    # ---- Groups 
    # <group> correspond to the start year (year n) of the hydrological year
    # Hydrological years are considered to start in october (year n) and end in september (year n+1)
    group = final_map.time.dt.year \
        + np.floor((final_map.time.dt.month + 2)/12) - 1
    group = group.astype(int)
    
    # ---- Aggregate values:
    if mode == 'sum':
        final_map = final_map.groupby(group).sum(min_count = 1)
    
    elif mode == 'min':
        final_map = final_map.groupby(group).min()
        
    elif mode == 'max':
        final_map = final_map.groupby(group).max()
        
    elif mode == 'mean':
        final_map = final_map.groupby(group).mean()
    
    elif mode == 'ratio_precip': # values expressed as pourcentages of annual PRETOT
        filename_pretot = f"PRETOT_{file_suffix}"
        filepath_pretot = os.path.join(file_folder, filename_pretot)    
        with xr.open_dataset(filepath_pretot, 
                             decode_coords = 'all', 
                             decode_times = True) as pretot:
            pretot = pretot['PRETOT_Q'].sel(
                time = slice(f"{str(annual_bins[0][0][0])}-10-01", f"{str(annual_bins[-1][1][1])}-09-30")
                )
            
            allmonths_group = pretot.time.dt.year \
                + np.floor((pretot.time.dt.month + 2)/12) - 1
            allmonths_group = allmonths_group.astype(int)  
            
            final_map = ( final_map.groupby(group).sum(min_count = 1) \
                / pretot.groupby(allmonths_group).sum(min_count = 1) )*100
                
# =============================================================================
#         # This adjusts the scale based on max among all INDIVIDUAL YEARS
#         zmax = max([zmax, float(final_map.max())])
#         print("   . Color scale has been adjusted")
# =============================================================================
    
    elif mode == 'ratio': # values expressed as pourcentages of annual sums      
        allmonths_group = ds.time.dt.year \
            + np.floor((ds.time.dt.month + 2)/12) - 1
        allmonths_group = allmonths_group.astype(int)    
        
        final_map = ( final_map.groupby(group).sum(min_count = 1) \
            / ds.groupby(allmonths_group).sum(min_count = 1) )*100
            
# =============================================================================
#         # This adjusts the scale based on max among all INDIVIDUAL YEARS
#         zmax = max([zmax, float(final_map.max())])
#         print("   . Color scale has been adjusted")
# =============================================================================
    
    
    #%%% Heatmap plot
    # Add traces, one for each period
    for dates in annual_bins:  
        # ---- Compute the decade average
        temp_map = final_map.loc[{'group': slice(dates[0][0], dates[1][0])}].mean(dim = 'group')
        
# =============================================================================
#         # This adjusts the color based on max among all GROUPED YEARS
#         zmax = max([zmax, float(temp_map.max())])
#         # print("   . Color scale has been adjusted")
# =============================================================================
        
        # ---- Update texts and plot annotations
        if timemode == 'ONDJFM':
            suf_title.append((f"oct. {dates[0][0]}", f"mar. {dates[1][1]}"))
            suf_slider.append(f"{dates[0][0]}-{dates[1][1]}")
            dst_dir2 = 'semestriels'
        elif timemode == 'AMJJAS':
            suf_title.append((f"avr. {dates[0][1]}", f"sep. {dates[1][1]}"))
            suf_slider.append(f"{dates[0][1]}-{dates[1][1]}")
            dst_dir2 = 'semestriels'
        elif timemode == 'annual':
            suf_title.append((f"oct. {dates[0][0]}", f"sep. {dates[1][1]}"))
            suf_slider.append(f"{dates[0][0]}-{dates[1][1]}")
            dst_dir2 = 'annuels'

        # ---- Add the traces
        fig.add_trace(go.Heatmap(
            z = temp_map.values,
            x = temp_map.x.values,
            y = temp_map.y.values,
            name = var,
            showlegend = False,
            showscale = True,
            coloraxis = "coloraxis",
            visible = False, # only the first trace will be set to visible
            ))

        fig.update_traces(
            hoverinfo = 'all',
            hovertemplate = "<b>%{z} " + unit + "</b> <br> %{x} m <br> %{y} m <br>"
            )
        """
        Other related functions:
            https://plotly.com/python/choropleth-maps/
            https://plotly.com/python/mapbox-county-choropleth/ (idem but with layout)
            https://plotly.com/python/mapbox-density-heatmaps/
        """
                   
    # ---- Create and add slider
    """
    cf https://plotly.com/python/sliders/
    """
    steps = []
    for i in range(0, len(fig.data)):
        step = dict(
            method="update",
            args=[{"visible": [False] * len(fig.data)},
                  {"title": f'<b>{metadata_by_var[main_var][1]}<br>(moyennes des {suf_timemode[mode][timemode]})</b><br>de {suf_title[i][0]} à {suf_title[i][1]}'},
                  ],  # layout attribute
            label = suf_slider[i],
            # style = {'transform': 'rotate(45deg)'},
        )
        step["args"][0]["visible"][i] = True  # Toggle i'th trace to "visible"
        steps.append(step)
        
    # Make 1st trace visible
    fig.data[0].visible = True
    
    sliders = [dict(
        active = 0,
        currentvalue = {"prefix": "période : "},
        pad = {"t": 40},
        steps = steps,
    )]

    # ---- Layout
    fig.update_layout(
        sliders = sliders,
        title = {'font': {'size': 20},
                 'text': f'<b>{metadata_by_var[main_var][1]}<br>(moyenne des {suf_timemode[mode][timemode]})</b><br>de {suf_title[0][0]} à {suf_title[0][1]}', # title on the first appearing step
                 'xanchor': 'center',
                 'x': 0.5,
                 'yanchor': 'bottom',
                  'y': 0.95,
                 },
        xaxis = {'title': {'font': {'size': 16},
                           'text': 'x [m]'},
                 'type': 'linear',
                 'showgrid': False,
                 # 'range': tuple(map(range_function[parameters[0]], xlim)),
                 },
        yaxis = {'title': {'font': {'size': 16},
                           'text': 'y [m]'},
                 'type': 'linear',
                 'scaleanchor': 'x',
                 'showgrid': False,
                 # 'range': tuple(map(range_function[parameters[1]], ylim)),
                 },
        coloraxis = {
            "colorscale": colorscale,
            "colorbar": {
                'title': {'text': unit},
                },
            "cmin": zmin,
            "cmax": zmax,
            },
        width = 775,
        height = 775,
        images = [{
            'source': Image.open(
                os.path.join(root_folder, "cartes", "graticule.png")),
            'xref': "x", # "paper",
            'yref': "y", # "paper",
            'x': -40000, # float(ds.x.min() - xres/2),
            'y': 2850000, # float(ds.y.max() + yres/2),
            'sizex': 1320000, # float(ds.x.max() - ds.x.min() + xres),
            'sizey': 1320000, # float(ds.y.max() - ds.y.min() + yres),
            'sizing': "stretch",
            'opacity': 0.5,
            'layer': "above", # "below"
            }, {
            'source': Image.open(
                os.path.join(root_folder, "cartes", "departements.png")),
                # os.path.join(root_folder, "cartes", "departements_blc.png")),
            'xref': "x", # "paper",
            'yref': "y", # "paper",
            'x': -40000, # float(ds.x.min() - xres/2),
            'y': 2850000, # float(ds.y.max() + yres/2),
            'sizex': 1320000, # float(ds.x.max() - ds.x.min() + xres),
            'sizey': 1320000, # float(ds.y.max() - ds.y.min() + yres),
            'sizing': "stretch",
            'opacity': 0.5,
            'layer': "above", # "below"
            }, {
            'source': Image.open(
                os.path.join(root_folder, "cartes", "France.png")),
                # os.path.join(root_folder, "cartes", "France_blc.png")),
            'xref': "x", # "paper",
            'yref': "y", # "paper",
            'x': -40000, # float(ds.x.min() - xres/2),
            'y': 2850000, # float(ds.y.max() + yres/2),
            'sizex': 1320000, # float(ds.x.max() - ds.x.min() + xres),
            'sizey': 1320000, # float(ds.y.max() - ds.y.min() + yres),
            'sizing': "stretch",
            'opacity': 0.5,
            'layer': "above", # "below"
            }, {
                # BDT limite terre-mer
            'source': Image.open(
                os.path.join(root_folder, "cartes", "map_background.png")),
            'xref': "x", # "paper",
            'yref': "y", # "paper",
            'x': -40000, # float(ds.x.min() - xres/2),
            'y': 2850000, # float(ds.y.max() + yres/2),
            'sizex': 1320000, # float(ds.x.max() - ds.x.min() + xres),
            'sizey': 1320000, # float(ds.y.max() - ds.y.min() + yres),
            'sizing': "stretch",
            'opacity': 1,
            'layer': "below", # "below"
            },
            ],
    )
    """https://plotly.com/python/images/"""
    
    # Credits
    fig.add_annotation(xanchor = 'center',
                        xref = 'paper',
                        x = 0.38,
                        yref = 'paper',
                        y = 0.01,
                        yanchor = 'bottom',
                        font = {'size': 12},
                        text = "<i>Crédits : Données @Météo-France (SIM) ; Figure @Alexandre Coche</i>",
                        showarrow = False
                        )

    # ---- Save the .html figures
    version = 'v7'
    if not os.path.exists(os.path.join(root_folder, "cartes", version, dst_dir1, dst_dir2)):
        os.makedirs(os.path.join(root_folder, "cartes", version, dst_dir1, dst_dir2))
    
    fig.write_html(os.path.join(
        root_folder, "cartes", version, dst_dir1, dst_dir2,
        '_'.join([var,
                  timemode,
                  mode,
                  datetime.datetime.now().strftime("%Y-%m-%d_%Hh%M"),
                  ]) + '.html'
        )
    )
    
    # This creates the figure AND open it in the web browser
# =============================================================================
#     offline.plot(fig, filename = os.path.join(root_folder,
#                                 "cartes", version, dst_dir1, dst_dir2,
#                                    '_'.join([var,
#                                              timemode,
#                                              mode,
#                                              datetime.datetime.now().strftime("%Y-%m-%d_%Hh%M"),
#                                              ]) + '.html'
#                                    ))
# =============================================================================
    # div_html = offline.plot(fig, include_plotlyjs = False, output_type='div')
    """
    https://stackoverflow.com/questions/36262748/save-plotly-plot-to-local-file-and-insert-into-html
    Remember that you'll need to include the plotly js file for all these charts 
    to work.
    You could include: 
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script> 
    just before putting the div you got. If you put this js at the bottom of 
    the page, the charts won't work.
    """
    
    #%%% Display the run time
    now = datetime.datetime.now()
    print("Computation time:", now - start_time)
    
    
    #%%% Pipeline to plot all interesting maps
    """
    start_time = datetime.datetime.now()
    print("Start time: ", start_time.strftime("%Y-%m-%d %H:%M"))
    print("The generation of all interactive graphic files can take 20 min\n")
    
    folder = r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\8- Meteo\Surfex\SIM2\compressed"
    
    for timemode in ['annual', 'ONDJFM', 'AMJJAS']:
        for var in ['EVAP', 'ETP', 'PRETOT', 'DRAINC', 'RUNC']:
            smt.plot_map(var, mode = "sum", timemode = timemode, file_folder = folder)
        smt.plot_map('T', mode = "mean", timemode = timemode, file_folder = folder)
        smt.plot_map('TINF_H', mode = "min", timemode = timemode, file_folder = folder)
        smt.plot_map('TSUP_H', mode = "max", timemode = timemode, file_folder = folder)
        smt.plot_map('WG_RACINE', mode = "mean", timemode = timemode, file_folder = folder)
        smt.plot_map('SWI', mode = "mean", timemode = timemode, file_folder = folder)
    for timemode in ['annual', 'ONDJFM', 'AMJJAS']:
        for var in ['PRETOT', 'EVAP', 'ETP', 'DRAINC', 'RUNC']:
            smt.plot_map(var, mode = "ratio", timemode = timemode, file_folder = folder)
    for timemode in ['annual', 'ONDJFM', 'AMJJAS']:
        for var in ['EVAP', 'ETP', 'DRAINC', 'RUNC']:
            smt.plot_map(var, mode = "ratio_precip", timemode = timemode, file_folder = folder)
            
    # Display the run time:
    now = datetime.datetime.now()
    print("\nTotal computation time:", now - start_time)
    """
