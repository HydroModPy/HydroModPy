---
html_theme.sidebar_secondary.remove: true
---

# HydroModPy

Groundwater in a catchment, from one TOML file: where the water table sits, where it
reaches the ground, which streams it keeps flowing, and how all of it changes with the
seasons.

::::::{grid} 1 1 3 3
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

:::::{grid-item-card} Guides
:link: guides/index
:link-type: doc
:class-card: hmp-door

One task per page: describe a catchment, give K per zone, choose the recharge,
calibrate, fix a run that does not converge.
+++
Engineers and researchers who build a model
:::::

:::::{grid-item-card} Reference
:link: reference/index
:link-type: doc
:class-card: hmp-door

Every TOML parameter: what it asks, its unit and range, its default, and when it is
read.
+++
Anyone writing a TOML file
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

:::::{grid-item-card} What changed in the TOML
:link: reference/changes
:link-type: doc

Fields added, removed or changed since 2.0.0a1, computed from the models.
:::::

::::::

```{toctree}
:hidden:

Understand <understand/index>
Get started <get-started/index>
Guides <guides/index>
Reference <reference/index>
Theory <theory/index>
Contribute <contribute/index>
About <about/index>
```
