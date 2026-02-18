from hydromodpy.calibration import calibration_method
import pandas as pd

# Create a synthetic monthly recharge time series
time = list(range(1, 13))  # 1 à 12
rech = [40, 30, 25, 20, 18, 19, 22, 26, 31, 37, 40, 43]
rech_ts = pd.Series(rech, index=time, name='rech')
rech_ts.index.name = 'time'

calib = calibration_method.Calibration([1e-4, 1e-3, 1e-2], [0.01, 0.05, 0.1], rech_ts)
