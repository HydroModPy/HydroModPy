from hydromodpy.calibration import calibration_engine
import pandas as pd

# Create a synthetic monthly recharge time series
time = list(range(1, 13))  # 1 à 12
rech = [40, 30, 25, 20, 18, 19, 22, 26, 31, 37, 40, 43]
rech_ts = pd.Series(rech, index=time, name='rech')
rech_ts.index.name = 'time'

# Define parameters to calibrate and their bounds using a dictionnary
# each key is a parameter name and the value is a list with the lower and upper bounds of the parameter range to explore.
params_to_calibrate = {
    'K': [1e-5, 1e-1],
    'Sy': [0.03, 0.08]
}

# Define maximum number of simulations to run within the calibration process.
# The actual number of simulations will be determined by the number of parameters and the resolution of the parameter space exploration.
max_nb_sim = 25

# Define the objective function to use for evaluating the performance of each parameter combination.
obj_func = 'RMSE'

# Define the calibration method to use.
calib_method = 'explore'

#Proceed to calibration via clibration_engine
calib = calibration_engine.Calibration(params_to_calibrate, max_nb_sim, rech_ts, obj_func, calib_method)
calib_results_dict, calib_results_df = calib.explore()
calib.print_results(calib_results_df)
print(calib_results_df)
print(calib_results_dict)