# 1D unconfined aquifer with a material interface - calibration case

A Dupuit aquifer, linearized or Boussinesq, with two materials split at `x = xi`. A noisy head
chronicle forged from known values gives back `(Kam, Kav, Syam, Syav, xi)` through the
`hydromodpy.calibration` engine. `groundwater_1d/` is the simpler confined case.

`calibrate_groundwater` runs it from Python. It is exercised by
`tests/unit/validation_cases/test_unconfined_interface_1d.py`.
