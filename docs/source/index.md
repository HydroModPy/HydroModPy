---
html_theme.sidebar_secondary.remove: true
---

# HydroModPy

A Python toolbox for automated, reproducible, catchment-scale modeling of shallow
groundwater. One TOML file takes a catchment from its digital elevation model to a
calibrated model: where the water table sits, where it reaches the ground, which streams
it keeps flowing, and how all of it changes with the seasons.

:::{div} hmp-badges
{{ version_badge }} [![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-EPL--2.0-2563eb?style=flat-square)](https://github.com/HydroModPy/HydroModPy/blob/main/LICENSE)
[![Docs](https://img.shields.io/github/actions/workflow/status/HydroModPy/HydroModPy/docs-deploy-pages.yml?branch=main&style=flat-square&logo=githubactions&logoColor=white&label=docs)](https://docs.hydromodpy.fr/main/)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-D7FF64?style=flat-square&logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![DOI](https://img.shields.io/badge/DOI-10.5194%2Fhess--30--5571--2026-f59e0b?style=flat-square&logo=doi&logoColor=white)](https://doi.org/10.5194/hess-30-5571-2026)
[![Zenodo](https://img.shields.io/badge/Zenodo-10.5281%2Fzenodo.22141925-1682D4?style=flat-square&logo=zenodo&logoColor=white)](https://doi.org/10.5281/zenodo.22141925)
[![GitHub stars](https://img.shields.io/github/stars/HydroModPy/HydroModPy?style=flat-square&logo=github&color=181717)](https://github.com/HydroModPy/HydroModPy)
:::

```{important}
This documentation is for version {{ release }}. Install it
with `pip install hydromodpy`. Projects written for version 1 should stay pinned
to an exact tag such as `v1.0.0`.
```

::::::{grid} 1 1 2 2
:gutter: 3

:::::{grid-item-card} New here?
:link: get-started/index
:link-type: doc
:class-card: hmp-door

Install, run a first model in under a minute, then climb example 04 in six files, from the
shortest file that runs to the soil reservoir.
+++
User guide, getting started
:::::

:::::{grid-item-card} A task to do, a result to read
:link: user-guide/index
:link-type: doc
:class-card: hmp-door

Calibrate, run many catchments, share a run. Then read each map and each curve, and see how
far to trust it.
+++
User guide
:::::

:::::{grid-item-card} A key, a command, an output
:link: reference/index
:link-type: doc
:class-card: hmp-door

Every TOML parameter, every `hmp` command, the Python API and the outputs of a run, generated
from the code.
+++
Reference
:::::

:::::{grid-item-card} The equations and the checks
:link: theory/index
:link-type: doc
:class-card: hmp-door

The equations, in the order the water meets them, and every check of the code against a
reference.
+++
Theory
:::::

::::::

Looking for one parameter? {doc}`The whole file as a tree <reference/parameters/explorer>`
filters every key by name, value or word. You read a report made with HydroModPy and you do
not run it yourself? Start with {doc}`understand/what-it-computes`, then
{doc}`understand/reading-results`.

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

User guide <user-guide/index>
Reference <reference/index>
Theory <theory/index>
Contribute <contribute/index>
About <about/index>
```
