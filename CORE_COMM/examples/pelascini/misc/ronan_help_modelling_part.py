# -*- coding: utf-8 -*-
"""
Created on Thu May  5 15:06:03 2022

@author: ronan
"""

# Input recharge
bzh_rech = False
var = 'REC'
mod = 'REA'
# mod = 'NOR1'
sce = 'historic'
# sce = 'historic'
typ = 'monfmordsteady' # sinu / hist / proj
wr = True

# Choice temporal of the simulation
sim_state = 'transient' # 'steady' or 'transient'
init_rech = None # 'first'
period = [2015,2019] # recharge period
first = period[0]
last = period[1]
time_step = 'M' # or 'D'
actual_date = True # False if date is conceptual
start = str(period[0])+'-01-01' # necessary to specify the first time_step date

fhist = 1990
lhist = 1991

# Active of not modules
box = False # if True generate a rectangular model
sink_fill = False # permit to fill sinks
modpath_sim = False # run modpath particle tracking if True
verbose = False # add print of MODFLOW in console
post_process = False # print time_step

# Strcture of the model
lay_number = 1 # vertical discrtization
bottom = None # aquifer flat or not
thick_exp = 1 # exponential decay of K with nlay
cond_decay = 0 # exponential decay of K with depth
thick = 30 # m


BV.hydrodynamic(...)


success, flow_model = BV.run_modflow(ident=model_name,
                                     modpath_sim=modpath_sim,
                                     sink_fill=sink_fill,
                                     box=box,
                                     lay_number=lay_number,
                                     bottom=bottom,
                                     thick_exp=thick_exp,
                                     cond_decay=cond_decay,
                                     verbose=True,
                                     post_process=post_process, 
                                     init_rech=init_rech)

BV.matrix_modflow(success,
                  flow_model,
                  first_only = True,
                  watertable_elevation = True,
                  watertable_depth = True, 
                  seepage_areas = True,
                  outflow_drain = True,
                  groundwater_flux = True,
                  specific_discharge = False,
                  accumulation_flux = True,
                  perenn_intermit_shp = False,
                  groundwater_storage = True,
                  verbose = True,
                  export_tif = True)

# # Extract results
BV.results_modflow(ident=model_name,
                   actual_date=actual_date,
                   start=start,
                   time_step=time_step)

# # Plot maps
save_gif = False # save a gif after plots
Rech = flow_model.climatic
surf = modflow_display.SurfaceOutputs(Rech, simulations_folder, stable_folder, model_name, 
                                      types_obs, save_gif=save_gif, first_only=True,
                                      outflow=True, accflux=True, intermittency=True,
                                      chronics=True, sim_state=sim_state)