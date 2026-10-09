# Understand HydroModPy

HydroModPy simulates the groundwater of a {term}`catchment` from its relief, its geology and its
rainfall. It computes where the {term}`water table` is, where it reaches the surface, which
streams it feeds and how all this changes through the seasons. Every result depends on
assumptions. This part of the site says which ones, and how to read the maps without
over-interpreting them. It needs no prerequisite, and every technical term links to the
{doc}`glossary`.

## What you find here

::::{grid} 1 1 3 3
:gutter: 3

:::{grid-item-card} In five minutes
:link: in-five-minutes
:link-type: doc

One map and five sentences. Start here if you have to decide, fund or read a report.
:::

:::{grid-item-card} What the model computes
:link: what-it-computes
:link-type: doc

The water table, seepage, baseflow, stream intermittence, the water budget.
What they are computed from, with which assumptions, and what the model does not compute.
:::

:::{grid-item-card} Reading the results
:link: reading-results
:link-type: doc

One note per map and per curve of example 04: what to look at, what it does not show,
the pitfalls, and what makes it reliable or only indicative.
:::

:::{grid-item-card} How the model makes streams
:link: stream-network
:link-type: doc

Where the water table reaches the ground, how seepage draws a stream network,
and why it grows in winter and shrinks in summer.
:::

:::{grid-item-card} Scoring a simulated stream network
:link: network-metrics
:link-type: doc

How a simulated network is compared with a mapped one, and the difference
between a diagnostic and a criterion.
:::

:::{grid-item-card} How sure is the model?
:link: how-sure
:link-type: doc

Where the doubt comes from, why several answers can look equally good, and what a range or a
band tells.
:::

:::{grid-item-card} What "validated" means here
:link: what-validated-means
:link-type: doc

Numerical verification, calibration, validation and peer review: four kinds of evidence that
answer four questions.
:::

:::{grid-item-card} Where the data come from
:link: where-the-data-come-from
:link-type: doc

The producer and the fineness of each input, and what to do about licences.
:::

:::{grid-item-card} Can I check what was run?
:link: can-i-check-what-was-run
:link-type: doc

The record that comes with a run, and the commands that check it.
:::

:::{grid-item-card} Glossary
:link: glossary
:link-type: doc

The terms used on this site, with a short definition, and the setting in the configuration
file when there is one.
:::

::::

## When not to use this

HydroModPy is built for shallow groundwater at the scale of a catchment. Do not rely on it
for these cases, or only with an expert.

- **Deep or confined aquifers, and large sedimentary basins.** The model describes a shallow
  aquifer whose top rises and falls with the recharge. See the
  [limits in the theory](../theory/groundwater-flow.md#limits).
- **Aquifers where water moves mostly through conduits,** such as karst. The model treats the
  ground as a continuous porous medium.
- **Floods and river hydraulics.** In the default setup there is no water level, no flood and no
  travel time in the channel ({doc}`stream-network`).
- **Decisions at the scale of a field or a plot.** A cell is 75 m wide in example 04, and a map
  is read at the scale of the hillside.
- **Water quality,** unless a transport computation has been set up for it. The maps of this
  part of the site are about water, not about what it carries.
- **Climate projections taken as forecasts.** The model replays the forcing it is given. A
  projection is only as good as the climate data and the evaluation behind it.
- **A single result taken as certain.** Without a validation on data that the calibration has not
  seen, read a result as an indication ({doc}`what-validated-means`, {doc}`how-sure`).

## One catchment as a common thread

The pages rely on example 04 of HydroModPy: the Nançon catchment (Ille-et-Vilaine,
64.6 km²), simulated from 2000 to 2002 with a monthly step. The example shows how the
seepage network grows in winter and shrinks in summer, and how the
{term}`hydraulic conductivity` and the {term}`specific yield` of the aquifer are calibrated
against the {term}`mapped network` and against the flow measured at the outlet.

This is a demonstration example. Its results illustrate how to read the outputs. They are not
a study of the catchment.

## Who this is for, and where to go next

- You decide, you fund or you read a report based on HydroModPy: start with
  {doc}`in-five-minutes`, then {doc}`what-it-computes` and {doc}`reading-results`.
- You judge the quality of a result: {doc}`how-sure`, {doc}`what-validated-means`,
  {doc}`where-the-data-come-from` and {doc}`can-i-check-what-was-run`.
- You are building a model: the {doc}`staircase <../get-started/staircase/index>` builds one
  step by step, and the {doc}`reference <../reference/index>` describes each parameter.
- You are installing the tool for the first time: {doc}`../get-started/index`.

```{toctree}
:hidden:
:maxdepth: 1

in-five-minutes
what-it-computes
reading-results
stream-network
network-metrics
how-sure
what-validated-means
where-the-data-come-from
can-i-check-what-was-run
glossary
```
