# 1D transient groundwater calibration — demo

Analytic-grade 1D confined aquifer, implicit finite-difference recession.
Recovers `(T, S)` from a noisy head record at a mid-column well using the
`hydromodpy.calibration` engine.

Usage:

```bash
python -m validation_cases.calibration.groundwater_1d.run_case \
    --optimizer scipy_nelder_mead --max-iter 60
```

Also exercised by `tests/validation/calibration/test_groundwater_1d.py`.
