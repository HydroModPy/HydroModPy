# Guides

One task per page. The guides follow the order of the work: describe the catchment, set
the physics, bring the data, calibrate, read the outputs, and fix what breaks. A guide does
not repeat the reference. It embeds the rows it needs and links to their cards.

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} 1. Describe the catchment
The place, its edges, and the window of time.

- Basin and outlet {bdg-secondary}`not written in this mock-up`
- Boundaries and rivers {bdg-secondary}`not written in this mock-up`
- Time and initial state {bdg-secondary}`not written in this mock-up`
:::

:::{grid-item-card} 2. Set the physics
What the aquifer is made of, and what feeds it.

- {doc}`Give K and Sy per geological zone <k-per-zone>`
- {doc}`Choose how recharge enters the model <recharge>`
:::

:::{grid-item-card} 3. Bring the data
Rain, evapotranspiration, geology, the river network, the gauge.

- Data {bdg-secondary}`not written in this mock-up`
:::

:::{grid-item-card} 4. Calibrate
Fit parameters to observations.

- Calibrate {bdg-secondary}`not written in this mock-up`
:::

:::{grid-item-card} 5. Read the outputs
What a run writes, and how to read it back.

- Results and exports {bdg-secondary}`not written in this mock-up`
- Drive HydroModPy from Python {bdg-secondary}`not written in this mock-up`
:::

:::{grid-item-card} 6. When something breaks
Start from the symptom.

- {doc}`A run does not converge <non-convergence>`
- Troubleshooting by message {bdg-secondary}`not written in this mock-up`
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

Give K and Sy per geological zone <k-per-zone>
Choose how recharge enters the model <recharge>
A run does not converge <non-convergence>
Write a scenario by inheriting a file <inheritance>
Four calibrations to start from <calibration-recipes>
Calibrate on the stream network <stream-network-calibration>
```
