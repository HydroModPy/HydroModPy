---
html_theme.sidebar_secondary.remove: true
---

# HydroModPy

A Python toolbox for automated, reproducible, catchment-scale modelling of shallow
groundwater. One TOML file takes a catchment from its digital elevation model to a
calibrated model: where the water table sits, where it reaches the ground, which streams
it keeps flowing, and how all of it changes with the seasons.

:::{div} hmp-badges
{{ version_badge }}
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-EPL--2.0-2563eb?style=flat-square)](https://github.com/HydroModPy/HydroModPy/blob/main/LICENSE)
[![Docs](https://img.shields.io/github/actions/workflow/status/HydroModPy/HydroModPy/docs-deploy-pages.yml?branch=main&style=flat-square&logo=githubactions&logoColor=white&label=docs)](https://docs.hydromodpy.fr/main/)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-D7FF64?style=flat-square&logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![DOI](https://img.shields.io/badge/DOI-10.5194%2Fhess--30--5571--2026-f59e0b?style=flat-square&logo=doi&logoColor=white)](https://doi.org/10.5194/hess-30-5571-2026)
[![Zenodo](https://img.shields.io/badge/Zenodo-10.5281%2Fzenodo.22141925-1682D4?style=flat-square&logo=zenodo&logoColor=white)](https://doi.org/10.5281/zenodo.22141925)
[![GitHub stars](https://img.shields.io/github/stars/HydroModPy/HydroModPy?style=flat-square&logo=github&color=181717)](https://github.com/HydroModPy/HydroModPy)
:::

```{important}
This documentation follows the 2.0 pre-release line, version {{ release }}. Install it
with `pip install --pre hydromodpy`. Projects written for version 1 should stay pinned
to an exact tag such as `v1.0.0`.
```

::::::{grid} 1 1 2 2
:gutter: 3

:::::{grid-item-card} Understand
:link: understand/index
:link-type: doc
:class-card: hmp-door

What the maps and numbers of HydroModPy show, how to read them, and what they do not
say. In plain words, no prerequisites.
+++
Water managers, elected officials, consultancies, the public
:::::

:::::{grid-item-card} Reference
:link: reference/index
:link-type: doc
:class-card: hmp-door

Every TOML parameter, every `hmp` command and the Python API, generated from the code.
+++
Anyone writing a TOML file or a script
:::::

::::::

::::::{grid} 1 1 3 3
:gutter: 3

:::::{grid-item-card} Get started
:link: get-started/index
:link-type: doc

Install, then climb example 04 in six files, from the shortest file that runs to the
soil reservoir.
:::::

:::::{grid-item-card} Find a parameter
:link: reference/parameters/explorer
:link-type: doc

The whole file as a tree, filterable by key, value or word: *snap*, *conductivity*,
*recharge*, *voronoi*.
:::::

:::::{grid-item-card} Theory and validation
:link: theory/index
:link-type: doc

The equations, in the order the water meets them, and every check of the code
against a reference.
:::::

::::::

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

## Highlights

::::{grid} 1 2 3 3
:gutter: 3

:::{grid-item-card} Several solvers, one file
:link: reference/solvers
:link-type: doc

MODFLOW 6, MODFLOW-NWT and a Boussinesq solver for the flow; MODFLOW 6, MT3DMS and
MODPATH for solutes and particles.
:::

:::{grid-item-card} A typed configuration
:link: reference/parameters/index
:link-type: doc

One `HydroModPyConfig` root, every key typed and checked by Pydantic. The `hmp`
command runs the same file without writing any Python.
:::

:::{grid-item-card} From a DEM to a model
:link: reference/data-sources
:link-type: doc

Catchment delineation, forcing, mesh and observations from one configuration, with
public data downloaded and cached.
:::

:::{grid-item-card} Calibration
:link: reference/calibration-methods
:link-type: doc

Heads, discharge and mapped stream networks combined into calibrations you can replay,
on the distributed model or on a lumped GR4J model.
:::

:::{grid-item-card} Results you can reopen
:link: reference/cli/catalog
:link-type: doc

A catalog of runs, Zarr fields and Parquet tables, with exports to standard
geospatial formats.
:::

:::{grid-item-card} Checked against references
:link: theory/validation
:link-type: doc

Every validation test: the reference it compares with, the solvers it runs and the
thresholds it must stay under, read from the tests.
:::

::::

## What's new

Every notable change is recorded in the {doc}`changelog <about/changelog>`. The keys
added, removed or changed in the TOML file since the last release are listed, from the
models, in {doc}`reference/changes`.

## How to cite

If HydroModPy supports your work, please cite the companion technical note, published in
*Hydrology and Earth System Sciences* (2026,
[doi:10.5194/hess-30-5571-2026](https://doi.org/10.5194/hess-30-5571-2026)), and the
software, archived on Zenodo
([doi:10.5281/zenodo.22141925](https://doi.org/10.5281/zenodo.22141925)). {doc}`about/cite` gives BibTeX, RIS and plain-text versions; `CITATION.cff` at
the root of the repository is what GitHub shows behind "Cite this repository".

````{dropdown} BibTeX entries
:icon: book

```{hmp-citation} bibtex
```
````

Papers that use HydroModPy and the catchments where it has been deployed are listed in
{doc}`about/applications`.

## Authors and contact

````{dropdown} Authors and affiliations
:icon: people

```{hmp-authors}
```
````

For questions or collaboration requests:

- Alexandre Gauvain, `alexandre.gauvain.ag@gmail.com`
- Ronan Abhervé, `ronan.abherve@inrae.fr`
- Bug reports and feature requests: [GitHub issues](https://github.com/HydroModPy/HydroModPy/issues)
- Discussions: [Google Group](https://groups.google.com/g/hydromodpy)

```{toctree}
:hidden:

Home <self>
Understand <understand/index>
Get started <get-started/index>
Reference <reference/index>
Theory <theory/index>
Contribute <contribute/index>
About <about/index>
```
