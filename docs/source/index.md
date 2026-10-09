---
html_theme.sidebar_secondary.remove: true
---

# HydroModPy

HydroModPy computes where groundwater comes out of the ground and which streams it keeps
alive, month by month, for a whole catchment.

It is a Python toolbox for automated, reproducible, catchment-scale modelling of shallow
groundwater. One TOML file takes a catchment from its digital elevation model to a calibrated
model: where the water table sits, where it reaches the ground, which streams it keeps
flowing, and how all of it changes with the seasons.

:::{div} hmp-badges
[![version 2.0](https://img.shields.io/badge/version-2.0-f59e0b?style=flat-square){width=78px height=20px}](https://pypi.org/project/hydromodpy/)
[![licence EPL-2.0](https://img.shields.io/badge/license-EPL--2.0-2563eb?style=flat-square){width=100px height=20px}](https://github.com/HydroModPy/HydroModPy/blob/main/LICENSE)
:::

```{image} /_static/figures/hero/flow-intermittence-map.webp
:alt: Map of the Nançon catchment in 2002. Perennial streams in blue form a trunk and its main branches. Intermittent streams in orange sit at the upstream ends and on side branches. The rest of the catchment is dry, in gray.
:width: 560px
:align: center
```

*Streams that flow all year (blue) and part of the year (orange) in the Nançon catchment,
computed by the demonstration model of example 04. {doc}`How to read this map
<understand/reading-results>`.*

::::::{grid} 1 1 3 3
:gutter: 3

:::::{grid-item-card} {octicon}`light-bulb;1.4em` I need to understand a result
:link: understand/index
:link-type: doc
:class-card: hmp-door

What the maps and numbers show, how sure the model is, and what it does not say. In plain
words, no prerequisites.
:::::

:::::{grid-item-card} {octicon}`rocket;1.4em` I want to run my catchment
:link: get-started/index
:link-type: doc
:class-card: hmp-door

Install, then climb example 04 in six files, from the shortest file that runs to the soil
reservoir.
:::::

:::::{grid-item-card} {octicon}`search;1.4em` I look for a parameter
:link: reference/parameters/explorer
:link-type: doc
:class-card: hmp-door

The whole configuration file as a tree, filterable by key, value or word: *snap*,
*conductivity*, *recharge*, *voronoi*.
:::::

::::::

The other doors:

::::{grid} 1 1 3 3
:gutter: 2

:::{grid-item}
**{doc}`Reference <reference/index>`**
Parameters, commands, Python API.
:::

:::{grid-item}
**{doc}`Theory <theory/index>`**
The equations and their checks.
:::

:::{grid-item}
**{doc}`Contribute <contribute/index>`**
Architecture and how-tos.
:::

::::

## What HydroModPy does

Physically based groundwater models are expensive to deploy at the scale of a
catchment: data, mesh, parameters, calibration and post-processing rarely follow the
same path from one site to the next. HydroModPy turns the construction, the run, the
calibration and the analysis of a shallow groundwater model into one workflow that can
be replayed on many catchments, with the same inputs and the same outputs.

It automates the steps that take the most time:

1. **Catchment extraction** from a digital elevation model.
2. **Forcing and observations**: recharge, climate series, groundwater heads, gauged
   discharge, mapped stream networks and intermittency.
3. **Mesh and vertical discretisation** suited to shallow basement aquifers, with
   parameters given per zone or per cell, in steady state or in transient.
4. **Calibration** that combines heads, discharge and the extent of the stream network
   to constrain the hydraulic properties.
5. **Outputs that can be reopened**, stored with their provenance and the licence of
   the data they come from, then drawn as figures or exported to standard formats.

First a FloPy-driven MODFLOW-NWT toolbox, HydroModPy now runs several solvers behind
one configuration validated by Pydantic, and stores its runs in a columnar layout
(DuckDB catalog, Zarr fields, Parquet tables) that makes them reproducible and easy to
inspect.

## What's new

Every notable change is recorded in the {doc}`changelog <about/changelog>`. The keys
added, removed or changed in the TOML file since the last release are listed, from the
models, in {doc}`reference/changes`.

## Cite, authors, contact

The citation, the BibTeX entries, the technical note that describes the toolbox and the list
of authors are in {doc}`About </about/index>`, with the papers that use HydroModPy and the
catchments where it has been deployed. Questions and bug reports go to
[GitHub issues](https://github.com/HydroModPy/HydroModPy/issues) or to the
[Google Group](https://groups.google.com/g/hydromodpy).

```{toctree}
:hidden:

Understand <understand/index>
Get started <get-started/index>
Reference <reference/index>
Theory <theory/index>
Contribute <contribute/index>
About <about/index>
```
