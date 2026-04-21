# Brutsaert-Nieber recession calibration — demo

Analytical recession `dQ/dt = -a Q^b` with log-normal noise. Recovers
`(a, b)` using the `hydromodpy.calibration` engine.

Usage:

```bash
python -m validation_cases.calibration.recession_brutsaert.run_case \
    --optimizer scipy_nelder_mead --max-iter 100
```

Also exercised by `tests/validation/calibration/test_recession_brutsaert.py`.
