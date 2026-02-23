from hydromodpy.calibration import calibration_method
import pandas as pd



# Create a synthetic monthly recharge time series
# to replace by: user path or automatic data retrieving
time = list(range(1, 13))  # 1 à 12
rech = [40, 30, 25, 20, 18, 19, 22, 26, 31, 37, 40, 43]
rech_ts = pd.Series(rech, index=time, name='rech')
rech_ts.index.name = 'time'

# Observable reference
Q_obs = calibration_method.Q_brutsaert(rech_ts, 1E-3, 0.05) # To be replaced by reference observable


# Define parameters to calibrate and their bounds using a dictionnary
# each key is a parameter name and the value is a list with the lower and upper bounds of the parameter range to explore.
p=2
if p==1:
    params_to_calibrate = {
        'K': [1e-5, 1e-1]}
elif p==2:
    params_to_calibrate = {
        'K': [1e-5, 1e-1],
        'Sy': [0.03, 0.07]}
elif p==3:
    params_to_calibrate = {
        'K': [1e-5, 1e-1],
        'Sy': [0.03, 0.07],
        'Ss': [1,5]}

# Define maximum number of simulations to run within the calibration process.
# The actual number of simulations will be determined by the number of parameters and the resolution of the parameter space exploration.
max_nb_sim = 512

# Define the objective function to use for evaluating the performance of each parameter combination.
obj_func = 'NSE'

# Define the calibration method to use.
calib_method = 'regular_exploration'

#Proceed to calibration via clibration_engine and get results
calib_resultats = calibration_method.Calibration_method(
    params_to_calibrate,
    max_nb_sim,
    rech_ts,
    Q_obs,
    obj_func,
    calib_method,
    solver='Modflow')

calib_resultats.print_results()
my_results = calib_resultats.get_result()

# calib_resultats = calibration_engine.Calibration.simplex_calibration(calib_results)
# print('here:')
# print(calib_resultats)