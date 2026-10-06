# Guides

One task per page, in the order of the work: describe the catchment, set the physics,
bring the data, run and read the outputs, calibrate, study many catchments, and fix what
breaks. A guide does not repeat the reference: it embeds the keys it needs and links to
their cards.

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} 1. Describe the catchment
The place, its data, and the window of time.

- {doc}`Describe a catchment <describe-a-catchment>`
- {doc}`Get the data of a catchment <get-the-data>`
- {doc}`Use your own files <use-your-own-files>`
- {doc}`Work offline: caches and lockfiles <work-offline>`
- {doc}`Time, initial state and spin-up <time-and-initial-state>`
:::

:::{grid-item-card} 2. Set the physics
What the aquifer is made of, what feeds it, and where the water leaves.

- {doc}`Give K and Sy per geological zone <k-per-zone>`
- {doc}`Choose how recharge enters the model <recharge>`
- {doc}`Choose a solver <choose-a-solver>`
- {doc}`Lakes and reservoirs <lakes-and-reservoirs>`
- {doc}`Route streams with SFR <route-streams-with-sfr>`
- {doc}`Add a flow barrier <add-a-flow-barrier>`
- {doc}`Track particles <track-particles>`
:::

:::{grid-item-card} 3. Run and read the outputs
What a run writes, and how to read it back.

- {doc}`Results and exports <results-and-exports>`
- {doc}`Read a value at a point <read-a-value-at-a-point>`
- {doc}`Find, compare and clean runs <find-compare-and-clean-runs>`
- {doc}`Report on a catchment <report-on-a-catchment>`
- {doc}`Drive HydroModPy from Python <drive-from-python>`
:::

:::{grid-item-card} 4. Calibrate and compare
Fit parameters to observations, and compare runs or methods.

- {doc}`Calibrate <calibrate>`
- {doc}`Four calibrations to start from <calibration-recipes>`
- {doc}`Calibrate on the stream network <calibrate-on-the-stream-network>`
- {doc}`Read the uncertainty of a calibration <calibration-uncertainty>`
- {doc}`Compare runs and methods <compare-runs>`
:::

:::{grid-item-card} 5. Study many catchments
From one model to a region.

- {doc}`Select catchments in a region <select-catchments>`
- {doc}`Test a method on many catchments <test-a-method>`
:::

:::{grid-item-card} 6. When something breaks
Start from the symptom.

- {doc}`A run does not converge <non-convergence>`
- {doc}`Troubleshooting by message <troubleshooting>`
:::

::::

## Keep several scenarios

Once the first file runs, you will want variants of it: another recharge, another solver,
another list of exports. A file can inherit another one and write only the difference.

- {doc}`Write a scenario by inheriting a file <inheritance>`

Looking for one parameter instead of a task? Go to the
{doc}`reference <../reference/parameters/index>`. New to the project? Start with
{doc}`Get started <../get-started/index>`.

```{toctree}
:hidden:

describe-a-catchment
get-the-data
use-your-own-files
work-offline
time-and-initial-state
k-per-zone
recharge
choose-a-solver
lakes-and-reservoirs
route-streams-with-sfr
add-a-flow-barrier
track-particles
results-and-exports
read-a-value-at-a-point
find-compare-and-clean-runs
report-on-a-catchment
drive-from-python
calibrate
calibration-recipes
calibrate-on-the-stream-network
calibration-uncertainty
compare-runs
select-catchments
test-a-method
non-convergence
troubleshooting
inheritance
```
