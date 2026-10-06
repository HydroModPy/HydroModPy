# Understand HydroModPy

HydroModPy simulates the groundwater of a catchment from its relief, its geology and its
rainfall. It computes where the water table is, where it reaches the surface, which streams it
feeds and how all this changes through the seasons. Every result depends on assumptions. This
part of the site says which ones, and how to read the maps without over-interpreting them.

## What you find here

::::{grid} 1 1 3 3
:gutter: 3

:::{grid-item-card} What the model computes
:link: what-it-computes
:link-type: doc

The water table, seepage, baseflow, stream intermittence, the water budget.
What they are computed from, with which assumptions, and what the model does not compute.
:::

:::{grid-item-card} Reading the results
:link: reading-results
:link-type: doc

One note per map and per curve of example 04: what it shows, how to read it,
the pitfalls, and what makes it reliable or only indicative.
:::

:::{grid-item-card} Glossary
:link: glossary
:link-type: doc

The terms used on this site, a short definition, and the setting in the
configuration file when there is one.
:::

::::

## One catchment as a common thread

The pages rely on example 04 of HydroModPy: the Nançon catchment (Ille-et-Vilaine,
64.6 km²), simulated from 2000 to 2002 with a monthly timestep. The example shows how the
seepage network grows in winter and shrinks in summer, and how the hydraulic conductivity and
the specific yield of the aquifer are calibrated against the mapped network and against the
flow measured at the outlet.

This is a demonstration example. Its results illustrate how to read the outputs. They are not
a study of the catchment.

## Who this is for, and where to go next

- You decide, you fund or you read a report based on HydroModPy: start with
  {doc}`what-it-computes`, then {doc}`reading-results`.
- You are building a model: the {doc}`guides <../guides/index>` describe each task, and the
  {doc}`reference <../reference/index>` describes each parameter.
- You are installing the tool for the first time: {doc}`../get-started/index`.

```{toctree}
:hidden:
:maxdepth: 1

what-it-computes
reading-results
glossary
```
