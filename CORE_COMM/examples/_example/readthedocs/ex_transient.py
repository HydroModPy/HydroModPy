sim_state = 'transient'

# Update recharge
BV.forcing.update_recharge(values = rec/1000, sim_state=sim_state)

# Update effective porosity
P = 0.01 # -
BV.hydrodynamic.update_porosity(P)

# Set name of the model
model_name = sim_state

# RUN MODEL

# Launch a model
BV.run_modflow(ident=model_name, modpath_sim=False, calib=False, sink_fill=False, 
                lay_number=1, bottom=None, thick_exp=1., sea_level=None, cond_decay=0., 
                verbose=True)
print('Modeling process completed')

# Extract result chronics
BV.chronics_modflow(ident=model_name, mask=False, outlet_type=True, calib_only=False, 
                    first=first, last=last, time_step='monthly')
print('Result chronics extraction completed')

# Display simulation
plots.SurfaceOutputs(R, simulations_folder, stable_folder, model_name, types_obs, freq_interv=12, save_gif=True)

