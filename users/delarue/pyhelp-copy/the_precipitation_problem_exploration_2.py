# -*- coding: utf-8 -*-
"""
Created on Tue Jun  3 09:34:31 2025

@author: delarueo
--------------------------------------------------
Solving the preicpitation mystery 



"""

# -*- coding: utf-8 -*-
"""
Compare daily precipitation from CERRA model and MeteoSwiss station (Robbia)
Author: delarueo
"""
import os
import pandas as pd
import matplotlib.pyplot as plt
import toolbox_newFuns_ as tb

#%% FUNCTIONS VISUEL

# === PLOT CUMULATIVE COMPARISON ===
def plot_cumulative_precip(year):
    s = df_station_day[df_station_day.index.year == year]['total_precipitation'].cumsum()
    m = df_model_day[df_model_day.index.year == year]['tp'].cumsum()
    plt.figure(figsize=(10, 5))
    plt.plot(s.index.dayofyear, s, label='Station', color='blue')
    plt.plot(m.index.dayofyear, m, label='CERRA', color='red', linestyle='--')
    plt.title(f'Cumulative Precipitation – {year}')
    plt.xlabel('Day of Year')
    plt.ylabel('Cumulative Precipitation (mm)')
    plt.grid(True, linestyle=':')
    plt.legend()
    plt.tight_layout()
    plt.show()

# === PLOT DAILY COMPARISON ===
def plot_daily(year):
    s = df_station_day[df_station_day.index.year == year]
    m = df_model_day[df_model_day.index.year == year]
    fig, ax1 = plt.subplots(figsize=(12, 6))
    ax1.bar(s.index, s['total_precipitation'], width=1.0, label='Station (daily)', color='blue')
    ax1.plot(m.index, m['tp'], label='CERRA (daily)', linestyle='--', color='red')
    ax1.set_ylabel('Daily Precipitation (mm)')
    ax2 = ax1.twinx()
    ax2.plot(s.index, s['total_precipitation'].cumsum(), label='Station (cumulative)', color='navy')
    ax2.plot(m.index, m['tp'].cumsum(), label='CERRA (cumulative)', linestyle='--', color='darkred')
    ax1.set_title(f'Precipitation {year}: Daily & Cumulative')
    ax1.set_xlabel('Date')
    ax1.tick_params(axis='x', rotation=45)
    lines = ax1.get_lines() + ax2.get_lines()
    labels = [line.get_label() for line in lines]
    ax1.legend(lines, labels, loc='upper left')
    plt.tight_layout()
    plt.show()

# === PLOT SCATTER COMPARISON ===
def plot_scatter(log=False):
    combined = df_station_day[['total_precipitation']].join(df_model_day[['tp']], how='inner')
    plt.figure(figsize=(6, 6))
    if log:
        plt.loglog(combined['total_precipitation'], combined['tp'], 'o', alpha=0.5)
        plt.title('Log-Log Daily Precipitation Comparison')
    else:
        plt.plot(combined['total_precipitation'], combined['tp'], 'o', alpha=0.5)
        plt.plot([0, 150], [0, 150], 'k--')
        plt.title('Linear Daily Precipitation Comparison')
    plt.xlabel('Station (mm/day)')
    plt.ylabel('CERRA (mm/day)')
    plt.axis('equal')
    plt.grid(True, which='both', linestyle=':')
    plt.tight_layout()
    plt.show()

# === PLOT YEARLY COMPARISON BAR ===
def plot_yearly_bar():
    plt.figure(figsize=(10, 5))
    plt.bar(df_station_year.index.year, df_station_year['total_precipitation'], width=0.4, label='Station', align='center')
    plt.bar(df_model_year.index.year + 0.4, df_model_year['tp'], width=0.4, label='CERRA', align='center', color='red')
    plt.title('Yearly Total Precipitation')
    plt.xlabel('Year')
    plt.ylabel('Precipitation (mm)')
    plt.legend()
    plt.tight_layout()
    plt.show()

#%% === PARAMETERS ===
# cerra_path = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/total_precipitation/total_precipitation_urse.nc'
# station_path = 'L:/_poschiavino/_data/_meteoswiss/_ROB/order_127830_data.txt'
# output_vars = ['2m_temperature', 'total_precipitation']
# year = 2015
# y, x = 3, 3  # Grid index for Robbia

# Rechy version
cerra_path = 'Z:/_waterwise_data_process/_climate/_cerra_forecast/total_precipitation/total_precipitation_rech.nc'
station_path = 'Z:/_waterwise_teams_database/_save/_20250319/_time_series/_testing_sites/_rech/_climate/_liquid_precipitation/_observation/RADT/P.mm.csv'
output_vars = ['total_precipitation']
agg = {'total_precipitation': 'sum'}
year = 2015
y, x = 2, 2

# Info structure station data
time_label = 'date'
time_format = '%d.%m.%Y %H:%M'

#%% === LOAD CERRA DATA ===
print('>> Loading CERRA data')
cerra = tb.CERRA(cerra_path)
lat, lon = cerra.dataset['latitude'][y, x].values, cerra.dataset['longitude'][y, x].values
print(lat,lon)

tp_model = cerra.dataset['total_precipitation'].values[:, y, x]
df_model = pd.DataFrame({'time': pd.to_datetime(cerra.dataset['time'].values), 'tp': tp_model}).set_index('time')
df_model_day = df_model.resample('D').sum()
df_model_year = df_model.resample('Y').sum()

#%% === LOAD STATION DATA ===
print('>> Loading Station data')
mapping = {
    'tre200h0': '2m_temperature',
    'rre150h0': 'total_precipitation',
    'data': 'total_precipitation'
}

station_raw = pd.read_csv(station_path, sep=';')
station_raw.rename(columns=mapping, inplace=True)
print(station_raw)

df_station = pd.DataFrame()
df_station['time'] = pd.to_datetime(station_raw[time_label], format= time_format)
for var in output_vars:
    df_station[var] = pd.to_numeric(station_raw[var], errors='coerce')
df_station.set_index('time', inplace=True)

df_station_day = df_station.resample('D').agg(agg)
df_station_year = df_station.resample('Y').agg(agg)

#%% === RUN PLOTS ===
plot_cumulative_precip(year)
plot_daily(year)
plot_scatter(log=False)
plot_scatter(log=True)
plot_yearly_bar()
