# Recession of a hillslope aquifer - calibration case

The analytical recession of a hillslope aquifer, exponential or Boussinesq, gives the discharge
from `K` and `Sy`. A noisy discharge chronicle forged from known values gives them back through
the `hydromodpy.calibration` engine. `recession_brutsaert/` fits the empirical law
`dQ/dt = -a Q^b` instead, and this case reads `a` and `b` from `K` and `Sy` and calls that law.

`calibrate_brutsaert` runs it from Python. It is exercised by
`tests/regression/fast/calibration/` and by
`tests/unit/validation_cases/test_the_recession_case_scores_with_the_core_kernels.py`.
