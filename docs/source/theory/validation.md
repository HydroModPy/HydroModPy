# Validation

Each check below is a test of `tests/validation/`. It compares a computation
with a reference that HydroModPy did not produce: a closed-form solution, a
published MODFLOW 6 example, a manufactured solution, or a parameter that a
calibration must find again.

For every check the page gives the reference and its equations, the threshold
with the size of the signal it is read against, the value the last recorded
run measured, the outcome, and the date and commit of that run. A skipped test
is shown as skipped: it proves nothing. Where a threshold lets a known
discrepancy through, the case says so in a warning box at its top.

The measures come from a results snapshot committed next to this page,
`docs/source/theory/validation_results.json`. The nightly job writes the same
file for the code it runs. "When the checks run" below lists the jobs, read
from the workflow files, and the checks that no job runs.

```{hmp-validation}
```
