# Choice the state of the simulation
sim_state = 'steady' # steady
first = 2010
last = 2019
time_step = 'M'

# Recharge from a csv
rec = pd.read_csv(climate_path+'_REC_'+time_step+'.csv', sep=';', index_col=[0], parse_dates=True)
rec = rec[(rec.index.year>=first) & (rec.index.year<=last)]
rec = rec.squeeze()
BV.forcing.update_recharge(values = rec / 1000, sim_state=sim_state)

# Update hydrualic conductivity
K = 1e-5 * 3600 * 24 * 30 # m/second to m/month
BV.hydrodynamic.update_hyd_cond(K)

# Update aquifer thickness
E = 30 # m
BV.hydrodynamic.update_thickness(E)

# Set name of the model
model_name = sim_state

#%% RUN MODEL

# Launch a model
BV.run_modflow(ident=model_name, modpath_sim=False, calib=False, sink_fill=False, 
                lay_number=1, bottom=None, thick_exp=1., sea_level=None, cond_decay=0., 
                verbose=True)
print('Modeling process completed')

# Extract result chronics
BV.chronics_modflow(ident=model_name, mask=False, outlet_type=True, calib_only=False, 
                    first=first, last=last, time_step='monthly')
print('Result chronics extraction completed')