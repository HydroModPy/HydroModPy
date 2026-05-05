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
:doc:`../theory/index` or :doc:`../architecture/index`.

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
      :link: workflows/index
      :link-type: doc

      **Workflow families**
      ^^^
      Overview, simulation, testbed, calibration, batch, and comparison
      workflows.

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

Workspace-first organization
----------------------------

The cleanest long-term organization is to use the workspace layout as the
backbone, then describe workflows as operations that populate parts of that
workspace.

Read the documentation in this order when you want to avoid duplicates:

1. :doc:`../getting_started/workspace-layout` explains the durable folders:
   data cache, project TOMLs, generated child configs, runs, outputs, reports,
   and gallery evidence.
2. :doc:`workflows/index` explains which operation writes to those folders:
   overview for data identity cards, simulation for one persisted run, testbed
   for controlled variants, calibration for repeated candidate runs, batch for
   regional campaigns, and comparison for shared-case solver contrasts.
3. Topic guides such as :doc:`mesh`, :doc:`comparison`, and :doc:`calibration`
   should only route users to scientific, gallery, and architecture details;
   they should not duplicate the workflow walkthroughs.
4. The capability gallery should remain the evidence layer: stable figures,
   metrics, and reproducible examples that illustrate the workspace artifacts.

This structure keeps ``workspace layout`` as the index of where things live,
``workflow`` pages as the index of what operation creates them, and topic
pages as cross-cutting reading maps.

Topic guides
------------

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: mesh
      :link-type: doc

      **Mesh diagnostics**
      ^^^
      User-facing route through mesh examples, testbed-based discretization
      studies, scientific notes, and mesh architecture pages.

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
      :link: solver-process-map
      :link-type: doc

      **Solvers by process**
      ^^^
      Process-first map of flow, transport, postprocess, and display solver
      families.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: solver-choice
      :link-type: doc

      **Solver choice**
      ^^^
      Where to compare MODFLOW-NWT, MODFLOW 6, Boussinesq, meshes, and XT3D
      options.

Capability and API-oriented guides
----------------------------------

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: cli-reference
      :link-type: doc

      **CLI reference**
      ^^^
      Registered top-level commands, workflow flags, and nested command
      families.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: capability-matrix
      :link-type: doc

      **Capability matrix**
      ^^^
      What is supported, validated, demonstrated, and documented across
      workflows, solvers, data, figures, and exports.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: data/index
      :link-type: doc

      **Data loading**
      ^^^
      Retrieval workflow, provider matrix, local custom data conventions, cache
      inspection, lockfiles, and frozen runs.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: results-and-exports
      :link-type: doc

      **Results and exports**
      ^^^
      How runs are registered, queried, inspected, packaged, and exported to
      external formats.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: figures
      :link-type: doc

      **Figure catalog**
      ^^^
      Registered figure names, expected result families, and rendering entry
      points for reports and scripts.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: project-api
      :link-type: doc

      **Project API**
      ^^^
      Python lifecycle for workspace setup, geographic preprocessing, data,
      mesh, run execution, comparison, calibration, and cleanup.

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
   Workflow families <workflows/index>
   Workflow quick map <../getting_started/workflow-families>
   Workspace layout <../getting_started/workspace-layout>
   Project vs run <../getting_started/project-vs-run>
   mesh
   comparison
   calibration
   cli-reference
   capability-matrix
   Data loading <data/index>
   data-sources
   results-and-exports
   figures
   project-api
   solver-process-map
   solver-choice
   Reading result pages <../getting_started/reading-results-pages>
   Comparison workflow <../getting_started/comparison-workflow>
   Comparison output order <../getting_started/comparison-output-reading-order>
