#%% Script perso
# Bibliothèques installées par défaut
import sys
import os
# Removed unused imports: requests, datetime, logging
import pandas as pd
import plotly.offline as pyo
from rasterio.enums import Resampling
import rioxarray
import xarray
import rasterio

#% DOSSIER RACINE
try:
    from os.path import abspath, dirname
    root_dir = dirname(dirname(dirname(abspath(__file__))))
except NameError:
    root_dir = os.path.dirname(os.path.dirname(os.getcwd()))  # Pour les notebooks

sys.path.append(root_dir)

cwd = os.getcwd()
# print(f"Le répertoire courant est : {cwd}")
if cwd != root_dir:
    os.chdir(root_dir)
    # print(f"Répertoire racine défini : {root_dir}")
    
import users.bboivin
import importlib
importlib.reload(users.bboivin)
from users.bboivin import timeseriesplot, NetCDFReader, HubEau_requests_Nicolas

#%% Load NetCDF files
filepath = "C:\\Users\\basti\\Documents\\Output_HydroModPy\\LakeRes\\Meteo\\Historiques SIM2\\DRAINC_Q_SIM2_19900101_20250202.nc"
epsg_project = 2154
mask = "all"

reader_sim2_rec = NetCDFReader.NetCDFReader(filepath,
                                    epsg_project=epsg_project,
                                    mask=mask
                                    )
print("Metadata:", reader_sim2_rec.metadata)

reader_sim2_rec.spatial_aggregate(func="mean")
print("Spatially aggregated data by mean.")
print("Metadata:", reader_sim2_rec.metadata)

extraction_point = [331300, 6781273, 2154]
variable = "DRAINC_Q"
sim2_rec = reader_sim2_rec.to_df(extraction_point, var=variable)
print(f"Time series for variable '{variable}':")
print(sim2_rec)

filepath = "C:\\Users\\basti\\Documents\\Output_HydroModPy\\LakeRes\\Meteo\\Historiques SIM2\\RUNC_Q_SIM2_19700101_20250202.nc"

reader_sim2_runoff = NetCDFReader.NetCDFReader(filepath,
                                   epsg_project=epsg_project,
                                   mask=mask
                                   )
print("Metadata:", reader_sim2_runoff.metadata)

reader_sim2_runoff.spatial_aggregate(func="mean")
print("Spatially aggregated data by mean.")
print("Metadata:", reader_sim2_runoff.metadata)

variable = "RUNC_Q"
sim2_runoff = reader_sim2_runoff.to_df(extraction_point, var=variable)
print(f"Time series for variable '{variable}':")
print(sim2_runoff)

sim2_data = pd.merge(sim2_rec, sim2_runoff, on='time', suffixes=('_rec', '_runoff'))

sim2_data['Total_Q'] = sim2_data['DRAINC_Q'] + sim2_data['RUNC_Q']

print("Merged and summed dataframe:")
print(sim2_data[['time', 'Total_Q']])


#%% Load csv files
isba_rec = pd.read_csv("C:\\Users\\basti\\Documents\\Output_HydroModPy\\barrage_Cheze_SFR_LAK_2025-02-04_thick_35_hk_1.0e-04_sy_0.1_Isba_Brut\\results_stable\\climatic\\_REC_D.csv", sep=";")
isba_rec = isba_rec[[isba_rec.columns[0], "REC_REA_historic"]].copy()
isba_rec.columns = ["time", "Recharge_Isba"]
isba_rec["time"] = pd.to_datetime(isba_rec["time"], dayfirst=True)
print(isba_rec.head())



isba_runoff = pd.read_csv("C:\\Users\\basti\\Documents\\Output_HydroModPy\\barrage_Cheze_SFR_LAK_2025-02-04_thick_35_hk_1.0e-04_sy_0.1_Isba_Brut\\results_stable\\climatic\\_RUN_D.csv", sep=";")
isba_runoff = isba_runoff[[isba_runoff.columns[0], "RUN_REA_historic"]].copy()
isba_runoff.columns = ["time", "Runoff_Isba"]
isba_runoff["time"] = pd.to_datetime(isba_runoff["time"], dayfirst=True)
print(isba_runoff.head())

isba_data= pd.merge(isba_rec, isba_runoff, on='time', suffixes=('_rec', '_runoff'))
isba_data['Total_Q'] = isba_data['Recharge_Isba'] + isba_data['Runoff_Isba']

#%% Download Hydrometry data
bh_id = "J7364220"
hydrometry = HubEau_requests_Nicolas.Hydrometry(bh_id)
Station_Q = hydrometry.api_hubeau(bh_id)
print(Station_Q.head())
Station_Q["Q"] = (Station_Q["Q"]*86400) / 9680625 * 1000
Station_Q = Station_Q.reset_index()
Station_Q['t'] = pd.to_datetime(Station_Q['t'])

#%% Plot
open_browser = True

plotTS = timeseriesplot.TimeSeriesPlot(title="Name",
                                     x_axis_title="time",
                                     y_axis_title="mm/day",
                                     x_range=(2000, 2020),
                                     log_x=False,
                                     log_y=False
                                     )

plotTS.add_series(sim2_data,
                time_col='time',
                var_col='DRAINC_Q',
                color='blue',
                mode='lines',
                legend_name="Recharge SIM2"
                )

plotTS.add_series(sim2_data,
                time_col='time',
                var_col='Total_Q',
                color='darkblue',
                mode='lines',
                legend_name="Recharge + Runoff SIM2"
                )

plotTS.add_series(isba_data,
                time_col='time',
                var_col='Recharge_Isba',
                color='red',
                mode='lines',
                legend_name="Recharge Isba"
                )

plotTS.add_series(isba_data,
                time_col='time',
                var_col='Total_Q',
                color='darkred',
                mode='lines',
                legend_name="Recharge + Runoff Isba"
                )

plotTS.add_series(Station_Q,
                time_col='t',
                var_col='Q',
                color='black',
                mode='lines',
                legend_name="Débit J7364220"
                )

plotTS.show(open_browser=open_browser)
# %%
