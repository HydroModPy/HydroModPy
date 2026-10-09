# Guides

Each guide does one task, from a file that runs. It opens with what the task is, how long it
takes, what it needs and what it gives, shows the control figure of example 04 when one
exists, and ends with a table of what can go wrong. A guide does not repeat the reference: it embeds the keys it
needs and links to their cards.

The six groups follow the order of the work. The first four are a path: describe the
catchment, build the model, run it and read the outputs, then calibrate and compare. The
fifth is for a region or a project that lasts. The sixth starts from the symptom.

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} 1. Describe the catchment
The place, its data, and the window of time.

- {doc}`describe-a-catchment`
- {doc}`get-the-data`
- {doc}`use-your-own-files`
- {doc}`outside-france`
- {doc}`work-offline`
- {doc}`time-and-initial-state`
:::

:::{grid-item-card} 2. Build the model
What the aquifer is made of, what feeds it, where the water leaves, and the mesh.

- {doc}`k-per-zone`
- {doc}`recharge`
- {doc}`depth-and-substratum`
- {doc}`boundary-and-initial-conditions`
- {doc}`prepare-the-terrain`
- {doc}`choose-a-solver`
- {doc}`choose-and-build-the-mesh`
- {doc}`lakes-and-reservoirs`
- {doc}`route-streams-with-sfr`
- {doc}`add-a-flow-barrier`
- {doc}`add-wells`
- {doc}`transport-and-particles`
- {doc}`track-particles`
:::

:::{grid-item-card} 3. Run and read the outputs
Write the file, run it, and read what it wrote.

- {doc}`inheritance`
- {doc}`set-up-your-editor`
- {doc}`run-in-the-background`
- {doc}`drive-from-python`
- {doc}`read-the-results`
- {doc}`export-results`
- {doc}`read-a-value-at-a-point`
- {doc}`read-piezometers`
- {doc}`report-on-a-catchment`
:::

:::{grid-item-card} 4. Calibrate and compare
Fit parameters to observations, and compare methods.

- {doc}`calibrate`
- {doc}`calibration-recipes`
- {doc}`calibrate-on-the-stream-network`
- {doc}`score-two-maps`
- {doc}`calibration-uncertainty`
- {doc}`compare-runs`
- {doc}`sweep-a-parameter`
:::

:::{grid-item-card} 5. Many catchments and many runs
From one model to a region, and from one run to a project you can keep and share.

- {doc}`select-catchments`
- {doc}`test-a-method`
- {doc}`regional-lab`
- {doc}`several-projects`
- {doc}`find-and-compare-runs`
- {doc}`clean-and-reindex-runs`
- {doc}`share-a-run`
- {doc}`hand-off-to-gis`
- {doc}`audit-and-purge`
:::

:::{grid-item-card} 6. When something breaks
Start from the symptom.

- {doc}`non-convergence`
- {doc}`troubleshooting`
:::

::::

## Which guide for my question

| You want to | Go to |
|---|---|
| Look at a catchment before you model it | {doc}`describe-a-catchment` |
| Know whether `hmp run` skips a run that is identical to a finished one | {doc}`find-and-compare-runs` |
| Change one value and run again | {doc}`inheritance`, or {doc}`drive-from-python` for a loop |
| Get a file out of a run for a colleague | {doc}`export-results`, and {doc}`hand-off-to-gis` for a GIS |
| Fit K to a gauge | {doc}`calibrate` |
| Compare two solvers or two meshes on one case | {doc}`compare-runs` |
| Free disk, or rebuild an index that is stale | {doc}`clean-and-reindex-runs` |
| Understand an error message | {doc}`troubleshooting`, or {doc}`non-convergence` for a solver that stops |
| Get a TOML file checked while you type | {doc}`set-up-your-editor` |

Looking for one parameter instead of a task? Go to the
{doc}`reference <../reference/parameters/index>`. New to the project? Start with
{doc}`Get started <../get-started/index>`.

```{toctree}
:hidden:
:caption: Describe the catchment

describe-a-catchment
get-the-data
use-your-own-files
outside-france
work-offline
time-and-initial-state
```

```{toctree}
:hidden:
:caption: Build the model

k-per-zone
recharge
depth-and-substratum
boundary-and-initial-conditions
prepare-the-terrain
choose-a-solver
choose-and-build-the-mesh
lakes-and-reservoirs
route-streams-with-sfr
add-a-flow-barrier
add-wells
transport-and-particles
track-particles
```

```{toctree}
:hidden:
:caption: Run and read the outputs

inheritance
set-up-your-editor
run-in-the-background
drive-from-python
read-the-results
export-results
read-a-value-at-a-point
read-piezometers
report-on-a-catchment
```

```{toctree}
:hidden:
:caption: Calibrate and compare

calibrate
calibration-recipes
calibrate-on-the-stream-network
score-two-maps
calibration-uncertainty
compare-runs
sweep-a-parameter
```

```{toctree}
:hidden:
:caption: Many catchments and many runs

select-catchments
test-a-method
regional-lab
several-projects
find-and-compare-runs
clean-and-reindex-runs
share-a-run
hand-off-to-gis
audit-and-purge
```

```{toctree}
:hidden:
:caption: When something breaks

non-convergence
troubleshooting
```
