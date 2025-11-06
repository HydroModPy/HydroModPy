# -*- coding: utf-8 -*-
"""
 * Copyright (C) 2023-2025 Clément, Roques, Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

#%% ---- LIBRAIRIES

# PYTHON PACKAGES
import sys
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import datetime
from numpy import sqrt, mean
from hydromodpy.tools import get_logger

# ROOT DIRECTORY

from os.path import dirname, abspath
root_dir = dirname(dirname(dirname(abspath(__file__))))
sys.path.append(root_dir)
logger = get_logger(__name__)
logger.info("Root path directory is: %s", root_dir.upper())

# HYDROMODPY MODEULES

import hydromodpy
import importlib
importlib.reload(hydromodpy)

from hydromodpy.modeling.gr4j.gr4j_cal import gr4j_cal
from hydromodpy.modeling.gr4j.calibre_gr4j import calibre_gr4j
from hydromodpy.modeling.gr4j.ennash import ennash

import warnings
warnings.filterwarnings("ignore")

#%% Prepare the input data

example_path = os.path.join(root_dir, "modeling/gr4j")
data_path = os.path.join(example_path, "data")

data_name = 'L0123001.pkl' #data from the example in hydrogr https://github.com/SimonDelmas/hydrogr/tree/master
data_to_read = os.path.join(data_path, data_name)

figure_path = os.path.join(example_path, "figures")
os.makedirs(figure_path, exist_ok=True)  # Ensure the directory exists

output_path = os.path.join(example_path, "output")
os.makedirs(output_path, exist_ok=True)  # Ensure the directory exists

df = pd.read_pickle(data_to_read)
df.columns = ['date', 'precipitation', 'temperature', 'evapotranspiration', 'flow', 'flow_mm']
df.index = df['date']

# Create matrix input for gr4j
start = datetime.datetime(1984, 1, 1, 0, 0)
end = datetime.datetime(2012, 12, 31, 0, 0)
mask = (df.index >= start) & (df.index <= end)
data = df.loc[mask]

data_all = {
    'date': data['date'],
    'p': data['precipitation'],
    't': data['temperature'],
    'etp': data['evapotranspiration'],
    'q': data['flow_mm'],
    'view': np.ones(len(data)) * 0.1,
    'transform': '',
    'type': 'discharge'
}

#%% Plot the input dataset

f=2
fig, axs = plt.subplots(4, 1, figsize=(f*3, f*4))

# Plot Precipitation
axs[0].bar(data_all['date'], data_all['p'], color='blue')
axs[0].set_ylabel('Precipitation [mm/d]')
axs[0].set_xlim([start, end])
axs[0].set_xticklabels([])
axs[0].tick_params(axis='x', which='both', bottom=False, top=False, labelbottom=False)

# Plot Temperature
axs[1].plot(data_all['date'], data_all['t'], color='red')
axs[1].set_ylabel('Temperature [°C]')
axs[1].set_xlim([start, end])
axs[1].set_xticklabels([])
axs[1].tick_params(axis='x', which='both', bottom=False, top=False, labelbottom=False)

# Plot ETP
axs[2].bar(data_all['date'], data_all['etp'], color='cyan')
axs[2].set_ylabel('ETP [mm]')
axs[2].set_xlim([start, end])
axs[2].set_xticklabels([])
axs[2].tick_params(axis='x', which='both', bottom=False, top=False, labelbottom=False)

# Plot Specific Discharge
axs[3].semilogy(data_all['date'], data_all['q'], color='purple')
axs[3].set_ylabel('Specific Discharge [mm/d]')
axs[3].set_xlim([start, end])

# Save the plot
figure_filename = os.path.join(figure_path, 'model_inputs.png')
plt.tight_layout()
plt.savefig(figure_filename)
plt.show()

#%% To calibrate our model we select a sub-period from our dataset... 

start_calib = datetime.datetime(1992, 1, 1, 0, 0)
end_calib = datetime.datetime(2000, 12, 31, 0, 0)
mask_calib = (data.index >= start_calib) & (data.index <= end_calib)
data_calib = data.loc[mask_calib]

data_calib = {
    'date': data_calib['date'],
    'p': data_calib['precipitation'],
    't': data_calib['temperature'],
    'etp': data_calib['evapotranspiration'],
    'q': data_calib['flow_mm'],
    'view': np.ones(len(data_calib)) * 0.1,
    'transform': '',
    'type': 'discharge'
}

#%%... and we run the model starting by defining the initial values and ranges for all the parameters

logger.info('Starting GR4J parameter calibration')
"""
    MODEL PARAMETERS
        X1 : Production reservoir capacity [ mm]
        X2 : Underground exchange coefficient
        X3 : Routing reservoir capacity [ mm ] 
        X4 : Base time of HU1 unit hydrograph [ day ]
        X5 : Rain/snow separation temperature
        X6 : Melting temperature
        X7 : Melt factor HBV
        S0: initial filling of the production reservoir
        R0 : Initial filling of the routing reservoir      
"""

#X1 : Production reservoir capacity [ mm]
X1 = np.empty(3, dtype=object)
X1[0] = 100 #init
X1[1] = 0.1 #min
X1[2] = 1500 #max

#X2 : Underground exchange coefficient
X2 = np.empty(3, dtype=object)
X2[0] = 0.5 #init
X2[1] = -5 #min
X2[2] = 5 #max

#X3 : Routing reservoir capacity [ mm ] 
X3 = np.empty(3, dtype=object)
X3[0] = 100 #init
X3[1] = 0.1 #min
X3[2] = 500 #max

#X4 : Base time of HU1 unit hydrograph [day] 
X4 = np.empty(3, dtype=object)
X4[0] = 2 #init
X4[1] = 0.1 #min
X4[2] = 10 #max

#X5 : Rain/snow separation temperature
X5 = np.empty(3, dtype=object)
X5[0] = 1 #init
X5[1] = -1 #min
X5[2] = 2 #max

#X6 : Melting temperature
X6 = np.empty(3, dtype=object)
X6[0] = 0.1 #init
X6[1] = 0 #min
X6[2] = 10 #max

#X7 : Melt factor HBV
X7 = np.empty(3, dtype=object)
X7[0] = 0.5 #init
X7[1] = 0.1 #min
X7[2] = 10 #max

#S0: initial filling of the production reservoir
S0 = np.empty(3, dtype=object)
S0[0] = 0.5 #init
S0[1] = 0 #min
S0[2] = 1 #max

#R0: Initial filling of the routing reservoir 
R0 = np.empty(3, dtype=object)
R0[0] = 0.5 #init
R0[1] = 0 #min
R0[2] = 1 #max

parI9 = [X1[0],   X2[0],    X3[0],   X4[0],      X5[0],    X6[0],      X7[0],    S0[0],    R0[0]]
minI9 = [X1[1],   X2[1],    X3[1],   X4[1],      X5[1],    X6[1],      X7[1],    S0[1],    R0[1]]
maxI9 = [X1[2],   X2[2],    X3[2],   X4[2],      X5[2],    X6[2],      X7[2],    S0[2],    R0[2]]
# Model calibration
parameters, nash, bilan = calibre_gr4j('gr4j_cal', data_calib, data_calib['q'], parI9, minI9, maxI9)

logger.info('Calibration finished; running full simulation')

#%% Now we can model the full dataset and evaluate the quality of the fit

Qsim, output = gr4j_cal(parameters, data_all)

# Remove the first year used to warm up the model
date_output = data_all['date']
start = datetime.datetime(1990, 1, 1, 0, 0) 
mask = date_output.index >= start

def remove_dict(output_dict, mask):
    for key in output_dict:
        if key in ['transform', 'view', 'type']:
            continue  
        output_dict[key] = output_dict[key][mask]
    return output_dict

output_f = remove_dict(output, mask)
data_all_f = remove_dict(data_all, mask)
date_f = date_output.loc[mask]
Qsim_f = Qsim[mask]

# Define the validation period and compute RMSE and NSE
start_val = end_calib
end_val = datetime.datetime(2005, 12, 31, 0, 0)
mask_val = (date_f.index >= start_val) & (date_f.index <= end_val)

Qsim_val = output_f['Qsim'][mask_val]
Qobs_val = data_all_f['q'].loc[mask_val]

def filter_nan(values1, values2):
    mask = ~np.isnan(values1) & ~np.isnan(values2)
    return values1[mask], values2[mask]

x, y = filter_nan(Qsim_val, Qobs_val)

rmse = sqrt(mean((x - y) ** 2.0))
nse = ennash(y, x)

logger.info('Quality of fit on the full dataset')
logger.info('RMSE: %.4f', rmse)
logger.info('NSE: %.4f', nse)

#%% Plot results

t = date_f
start_visu = datetime.datetime(1990, 1, 1, 0, 0)

fig, axs = plt.subplots(2, 1, figsize=(8, 4))
axs[0].plot(t, data_all_f['q'], 'b', label='Data')
axs[0].plot(t, output_f['Qsim'], 'r', label='Model')
axs[0].set_ylabel('Specific Discharge [mm/d]')
axs[0].legend()
axs[0].set_xlim([start, end])
axs[0].set_ylim([0, 25])

axs[1].semilogy(t, data_all_f['q'], 'b', label='Data')
axs[1].semilogy(t, output_f['Qsim'], 'r', label='Model')
axs[1].set_ylabel('Specific Discharge [mm/d]')
# ax[1].legend()
axs[1].set_xlim([start, end])

# Save the plot
figure_filename = os.path.join(figure_path, 'model_results_Qsim.png')
plt.tight_layout()
plt.savefig(figure_filename)
plt.show()

#%% Some additional plots 

fig, axs = plt.subplots(3, 1, figsize=(8, 6))
axs[0].plot(t, output['n'], 'r')
axs[0].set_ylabel('Snow store [mm]')
axs[0].set_xlim([start, end])

axs[1].plot(t, output['r'], 'b', label='routing')
axs[1].plot(t, output['s'], 'm', label='production')
axs[1].legend()
axs[1].set_ylabel('GW store [mm]')
axs[1].set_xlim([start, end])

axs[2].plot(t, output['pr'], 'b', lw=0.5)
axs[2].set_ylabel('percolation to routing store [mm/d]')
axs[2].set_xlim([start, end])
# print(output['pr'].mean())
# print(output['pr'].mean())
# axs[2].set_yscale('log')

# Save the plot
figure_filename = os.path.join(figure_path, 'model_results_outputs.png')
plt.tight_layout()
plt.savefig(figure_filename)
plt.show()

fig, ax = plt.subplots(1, 1, figsize=(5, 5))
ax.boxplot(output['pr'])
ax.set_yscale('log')

#%% Convert the output dict into a dataframe including t and csv file with the model outputs

output_df = pd.DataFrame(output_f)
output_df.index = date_f

# Save the DataFrame to a CSV file
output_csv_path = os.path.join(output_path, 'model_outputs.csv')
output_df.to_csv(output_csv_path)

logger.info('Model outputs saved to %s', output_csv_path)

#%% Notes
