User Guide
==========

This section groups the operational documentation that sits after the first
quickstart and before the low-level developer/API reference.

Use it when you already know how to launch HydroModPy, but need to understand
which workflow to run, how projects and runs are organized, how to compare
outputs, or where to find the scientific and architecture details behind a
topic.

If this is your first visit, start with :doc:`../getting_started/index`
instead. If you want equations or implementation diagrams, jump directly to
:doc:`../scientific/index` or :doc:`../architecture/index`.

Core concepts
-------------

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: ../seven-modes
      :link-type: doc

      **Usage modes**
      ^^^
      CLI TOML, JSON payloads, Python configuration, notebooks, and low-level
      primitives.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: ../getting_started/workflow-families
      :link-type: doc

      **Workflow families**
      ^^^
      Overview, simulation, mesh, calibration, batch, and comparison workflows.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: ../getting_started/workspace-layout
      :link-type: doc

      **Workspace layout**
      ^^^
      Where HydroModPy stores inputs, caches, generated artifacts, runs, and
      reports.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: ../getting_started/project-vs-run
      :link-type: doc

      **Project vs run**
      ^^^
      The distinction between reusable project state and one persisted model
      execution.

Topic guides
------------

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: mesh
      :link-type: doc

      **Mesh workflows**
      ^^^
      User-facing route through mesh examples, diagnostics, scientific notes,
      and mesh architecture pages.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: comparison
      :link-type: doc

      **Comparison workflows**
      ^^^
      How to run shared-case comparisons and how to read their generated
      metrics and figures.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: calibration
      :link-type: doc

      **Calibration workflows**
      ^^^
      Entry points for inverse problems, calibration architecture, and
      calibration benchmark pages.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: data/index
      :link-type: doc

      **Data loading**
      ^^^
      Retrieval workflow, provider matrix, local custom data conventions,
      cache inspection, lockfiles, and reproducible runs.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: solver-choice
      :link-type: doc

      **Solver choice**
      ^^^
      Where to compare MODFLOW-NWT, MODFLOW 6, Boussinesq, meshes, and XT3D
      options.

Reading outputs
---------------

Use these pages once you have generated or opened result pages:

- :doc:`../getting_started/reading-results-pages` explains how to read gallery,
  comparison, and validation pages.
- :doc:`../getting_started/comparison-output-reading-order` gives the reading
  order for comparison artifacts.

.. toctree::
   :maxdepth: 2
   :hidden:

   Usage modes <../seven-modes>
   Workflow families <../getting_started/workflow-families>
   Workspace layout <../getting_started/workspace-layout>
   Project vs run <../getting_started/project-vs-run>
   mesh
   comparison
   calibration
   Data loading <data/index>
   solver-choice
   Reading result pages <../getting_started/reading-results-pages>
   Comparison workflow <../getting_started/comparison-workflow>
   Comparison output order <../getting_started/comparison-output-reading-order>
