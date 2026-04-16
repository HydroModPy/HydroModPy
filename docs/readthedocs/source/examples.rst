Examples
=================

Each example ships as both a notebook and a Python script so you can replay the
workflow in your IDE or on Read the Docs. Browse the gallery below to open the
scenario you need.

.. important::

   If you are new to HydroModPy, do not start by scanning the full notebook
   inventory below. Open :doc:`getting_started/index` first, then return here
   once you know which workflow family you want.

- **Pip installations** – the PyPI wheel does not include the `examples/`
  directory. Download the full archive from
  https://github.com/HydroModPy/HydroModPy/archive/refs/heads/main.zip
  and extract the `examples/` folder where you run the project.
- **Conda / source installations** – the cloned repository already provides
  `examples/`, keep it in place so the relative paths used in the scripts remain valid.

First-visit path
----------------

If you want a recommended first path instead of browsing the full notebook
inventory, start with the guided entry points below.

1. Open :doc:`getting_started/index`.
2. Run the data-overview walkthrough before a full solver workflow.
3. Return to the notebook gallery only after you know which example family you
   want.

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: getting_started/index
      :link-type: doc

      **Getting started**
      ^^^
      Choose a first workflow, understand the main parameter groups, and follow
      guided walkthroughs for data overview and end-to-end simulation.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: capability_gallery/index
      :link-type: doc

      **Capability gallery**
      ^^^
      Curated static pages covering support building, workflow execution,
      solver comparison, validation, and calibration.

Choose the right entry point
----------------------------

.. list-table::
   :header-rows: 1
   :widths: 28 30 42

   * - If your goal is to...
     - Open this
     - Why this is the right starting point
   * - Follow a recommended first workflow
     - :doc:`getting_started/index`
     - It gives you the shortest path from installation to a first meaningful
       run, with parameter-reading help.
   * - Browse every teaching notebook and replayable script
     - :ref:`examples-notebook-gallery`
     - This is the full inventory, useful once you already know which family
       of examples you need.
   * - Inspect stable, curated result pages
     - :doc:`capability_gallery/index`
     - It is the best entry point when you want quick visual orientation,
       solver comparisons, or validation pages without opening editable
       workspaces first.

Illustrated capability gallery
------------------------------

The capability gallery complements the notebooks with a curated set of static,
versioned figures generated from reproducible examples, comparisons,
validation cases, and calibration benchmarks.
The documentation build does not execute these cases; it only reads the
committed PNG and JSON artifacts produced by ``python -m tools.doc_gallery``.

.. _examples-notebook-gallery:

Notebook gallery
----------------

Each notebook now opens with an ``Example Parameters`` block that summarizes the
main case-specific choices before the code cells: extraction mode, main flow
settings, and any parameter sweeps explored later in the notebook.

.. nbgallery::
    notebooks/example_00
    notebooks/example_01
    notebooks/example_02
    notebooks/example_03
    notebooks/example_04
    notebooks/example_05
    notebooks/example_06
    notebooks/example_07
    notebooks/example_08
    notebooks/example_09
    notebooks/example_10
    notebooks/example_11

.. warning::
   Some interactive figures (Plotly scenes, GIF animations, etc.) are hidden in
   the static documentation. Run the notebooks locally to see the full content.

.. toctree::
   :hidden:
   :maxdepth: 1

   getting_started/index
   capability_gallery/index
