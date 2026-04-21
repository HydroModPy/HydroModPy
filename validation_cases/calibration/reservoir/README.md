# Lumped reservoir calibration — demo

Single-reservoir ODE with non-linear outlet (`dh/dt = Q_in - k h^n`) plus a
two-reservoir-in-series variant. Recovers `(k, n)` or `(k1, k2)` from a
noisy outflow record using the `hydromodpy.calibration` engine.

Usage:

```bash
python -m validation_cases.calibration.reservoir.run_case \
    --variant one --optimizer scipy_nelder_mead
python -m validation_cases.calibration.reservoir.run_case \
    --variant two --optimizer scipy_de --max-iter 100
```

Also exercised by `tests/validation/calibration/test_reservoir.py`.
