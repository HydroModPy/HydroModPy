sim_state = 'transient'

# Update recharge
BV.forcing.update_recharge(values = rec/1000, sim_state=sim_state)

# Update effective porosity
P = 0.01 # -
BV.hydrodynamic.update_porosity(P)

# Set name of the model
model_name = sim_state
