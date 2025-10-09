# -*- coding: utf-8 -*-
"""
Created on Fri Feb 21 11:59:08 2025

@author: delarueo
"""

import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import math as m
import matplotlib.dates as mdates
from datetime import datetime, timedelta


data_path = 'L:/_poschiavino/_data/_boreholes/_pore_pressure/'
save_path = 'M:/general/poschiavino/data_visualisation/'

list_bh = ['01','2','3','04','05','8','11','12','13','16','45','46','47']
nb_bh = len(list_bh)
list_study = ['3','04','12']
labels = ['btw','urse','below Palü']
#%% filter un realistic value
 
# Choose variable extremum value
T_ext = [-5,15]      # °C
p_ext = [2000,3000]

labels = ['T1_degC','T2_degC','P1_masl','P2_masl']
boundaries = {'T1_degC': T_ext,
              'T2_degC': T_ext,
              'P1_masl': p_ext,
              'P2_masl': p_ext}

def filter_col(data, exts, label):
    data.loc[(data[label] < exts[0]) | (data[label] > exts[1]), label] = np.nan

    
def filter_cols(data, boundaries, labels):
    for label in labels:
        exts = boundaries[label]
        filter_col(data,exts,label)       




#%% load and plot all data
ncols = nb_bh//2+1
nrows = 4
fig, axis = plt.subplots(nrows,ncols,figsize = (5*ncols,4*nrows))


period = [datetime(2010, 1, 1),datetime(2025, 1, 1)]
T_lim = [0,8]      # °C
p_lim = [2000,2600] #  

for i in range(nb_bh):
    
    r = int(i>ncols-1)*nrows//2 
    c = i%(ncols)
    print(f'{r} {c}')
    
    bh = list_bh[i]
    # label = labels[i]
    
    id_bh = f'KB{bh}'
    print(f'>>> {id_bh}')
    file_path = f'{data_path}{id_bh}/{id_bh}.txt'
    
    df = pd.read_csv(file_path,low_memory=False)  
    df['time'] = pd.to_datetime(df['Date'])
    
    filter_cols(df, boundaries, labels)
      
    df.plot(ax = axis[r][c], x = 'time',  y =['T1_degC', 'T2_degC'])#,marker = '.',ls = '')
    df.plot(ax = axis[r+1][c], x = 'time', y =['P1_masl', 'P2_masl'])#,marker = '.',ls = '')
    # df.plot(ax = axis[2], x = 'time', y =['Bat'])    
        
    axis[r][c].set_ylim(T_lim)
    axis[r][c].set_xlim(period)
    
    
    axis[r+1][c].set_ylim(p_lim)
    axis[r+1][c].set_xlim(period)
    
    axis[r][c].set_xlabel('')
    
    if r<nrows-1: 
        axis[r][c].set_xticklabels([])
        axis[r+1][c].set_xticklabels([])
        
        axis[r+1][c].set_xlabel('')
        
    axis[r][c].set_title(id_bh)
    
axis[0][0].set_ylabel('Temperature [°C]')
axis[2][0].set_ylabel('Temperature [°C]')
axis[1][0].set_ylabel('Pressure [Pa]')
axis[3][0].set_ylabel('Pressure [Pa]')

#%% load and plot focus data
study_id = '20250224'
list_focus = ['01','2','3','11','12','04']
nb_bh = len(list_focus)
titles = ['LAGO BLANCO','PADÜ','VAL VARUNA URSE']


ncols = 3
nrows = 4
fig, axis = plt.subplots(nrows,ncols,figsize = (5*ncols,4*nrows))


period = [datetime(2010, 1, 1),datetime(2026, 1, 1)]
T_lim = [1,6]      # °C
p_lim = [2100,2500] #  

for i in range(nb_bh):
    
    r = int(i>ncols-1)*nrows//2 
    c = i%(ncols)
    print(f'{r} {c}')
    
    bh = list_focus[i]
    # label = labels[i]
    
    id_bh = f'KB{bh}'
    print(f'>>> {id_bh}')
    file_path = f'{data_path}{id_bh}/{id_bh}.txt'
    
    df = pd.read_csv(file_path,low_memory=False)  
    df['time'] = pd.to_datetime(df['Date'])
    filter_cols(df, boundaries, labels)
      
    df.plot(ax = axis[r][c], x = 'time',  y =['T1_degC', 'T2_degC'])#,marker = '.',ls = '')
    df.plot(ax = axis[r+1][c], x = 'time', y =['P1_masl', 'P2_masl'])#,marker = '.',ls = '')
    # df.plot(ax = axis[2], x = 'time', y =['Bat'])    
        
    axis[r][c].set_ylim(T_lim)
    axis[r][c].set_xlim(period)
    
    
    axis[r+1][c].set_ylim(p_lim)
    axis[r+1][c].set_xlim(period)
    
    axis[r][c].set_xticklabels([])
    axis[r][c].set_xlabel('')
    
    if r<nrows-2:         
        axis[r+1][c].set_xticklabels([])        
        axis[r+1][c].set_xlabel('')
    
    if r == 0 :
        ttl = f'{titles[c]}\n{id_bh}'
    else:
        ttl = id_bh
    
    axis[r][c].set_title(ttl)
    
axis[0][0].set_ylabel('Temperature [°C]')
axis[2][0].set_ylabel('Temperature [°C]')
axis[1][0].set_ylabel('Pressure [Pa]')
axis[3][0].set_ylabel('Pressure [Pa]')

plt.tight_layout()  # Adjust the layout to avoid clipping
plt.savefig(f'{save_path}temp_pres_{study_id}.png')

#%% load and plot focus data - separate plot

list_focus = ['01','2','3','11','12','04']
nb_bh = len(list_focus)


ncols = 1
nrows = 2


period = [datetime(2010, 1, 1),datetime(2026, 1, 1)]
T_lim = [1,6]      # °C
p_lim = [2100,2500] #  

for i in range(nb_bh):
    
    r = 0
    c = 0
    
    bh = list_focus[i]
    # label = labels[i]
    
    id_bh = f'KB{bh}'    
    print(f'>>> {id_bh}')
    
    file_path = f'{data_path}{id_bh}/{id_bh}.txt'
    fig, axis = plt.subplots(nrows,ncols,figsize = (5,4*2))
    df = pd.read_csv(file_path,low_memory=False)  
    df['time'] = pd.to_datetime(df['Date'])
    filter_cols(df, boundaries, labels)
      
    df.plot(ax = axis[r], x = 'time',  y =['T1_degC', 'T2_degC'])#,marker = '.',ls = '')
    df.plot(ax = axis[r+1], x = 'time', y =['P1_masl', 'P2_masl'])#,marker = '.',ls = '')
    # df.plot(ax = axis[2], x = 'time', y =['Bat'])    
        
    # axis[r].set_ylim(T_lim)
    axis[r].set_xlim(period)
    
    
    # axis[r+1].set_ylim(p_lim)
    axis[r+1].set_xlim(period)
    
    axis[r].set_xticklabels([])
    axis[r].set_xlabel('')
    
    if r<nrows-2:         
        axis[r+1].set_xticklabels([])        
        axis[r+1].set_xlabel('')
    

    ttl = id_bh
    
    axis[r].set_title(ttl)
    
    axis[0].set_ylabel('Temperature [°C]')
    axis[1].set_ylabel('Pressure [Pa]')
    
    plt.tight_layout()  # Adjust the layout to avoid clipping
    plt.savefig(f'{save_path}temp_pres_{id_bh}.png')
    
    #%%
    
# id_bh = f'KB11'
# print(f'>>> {id_bh}')
# file_path = f'{data_path}{id_bh}/{id_bh}.txt'

# df = pd.read_csv(file_path,low_memory=False)  
# df['time'] = pd.to_datetime(df['Date'])

# # print(df)

# fig, axis = plt.subplots(2,1,figsize = (5,6))

# df.plot(ax = axis[0], x = 'time',  y =['T1_degC', 'T2_degC'])#,marker = '+',ls = '')
# df.plot(ax = axis[1], x = 'time', y =['P1_masl', 'P2_masl'])#,marker = '+',ls = '')
# # df.plot(ax = axis[2], x = 'time', y =['Bat'])


# period = [datetime(2010, 8, 10),datetime(2024, 12, 12)]
# axis[0].set_ylabel('Temperature °C')
# axis[0].set_ylim([2.8,4])
# # axis[0].set_xticklabels([])
# axis[0].set_xlim(period)

# # axis[1].set_xticklabels([])
# # axis[1].set_xlabel('')
# axis[1].set_ylabel('Pression')
# axis[1].set_ylim([2400,2500])
# axis[1].set_xlim(period)

# axis[0].set_title(id_bh)    