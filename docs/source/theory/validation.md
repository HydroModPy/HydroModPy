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
`docs/source/theory/validation_results.json`. When the site is deployed, the
results the nightly jobs uploaded for the branch, if any, replace older ones.
Each case gives the date and commit of the run its numbers come from. "When the
checks run" below lists the jobs, read from the workflow files, and the checks
that no job runs.

```{hmp-validation}
```

## Two solvers on one catchment

The cases above compare each solver with an exact solution. A catchment has
none, so the reference model of example 04 is run twice from the same file:
once with MODFLOW 6, once with MODFLOW-NWT. Only the solver of the flow process
changes. `tools/docs/figures/render_ex04_figures.py` (group `solvers`) makes both
runs and draws the figures below; `tools/docs/figures/figures.toml` keeps the
command behind each one.

::::{grid} 1 1 2 2
:gutter: 2

:::{grid-item}
```{figure} /_static/figures/solvers/nancon_intermittence_mf6_hydrograph_sim_obs.webp
:alt: Simulated and observed monthly discharge at the outlet of the Nançon catchment, 2000 to 2002, run with MODFLOW 6.

Discharge at the outlet, MODFLOW 6.
```
:::

:::{grid-item}
```{figure} /_static/figures/solvers/nancon_intermittence_nwt_hydrograph_sim_obs.webp
:alt: Simulated and observed monthly discharge at the outlet of the Nançon catchment, 2000 to 2002, run with MODFLOW-NWT.

Discharge at the outlet, MODFLOW-NWT.
```
:::

::::

```{figure} /_static/figures/solvers/side_by_side.webp
:alt: Groundwater head of the Nançon catchment at one date, MODFLOW-NWT on the left and MODFLOW 6 on the right, on one colour scale.

Groundwater head at one date: MODFLOW-NWT on the left, MODFLOW 6 on the right, on one colour scale.
```

```{figure} /_static/figures/solvers/difference_map.webp
:alt: Head of MODFLOW-NWT minus head of MODFLOW 6, cell by cell, at the same date.

Head of MODFLOW-NWT minus head of MODFLOW 6, cell by cell, at the same date.
```
