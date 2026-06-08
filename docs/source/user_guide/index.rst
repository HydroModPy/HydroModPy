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
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: config_reference/index
      :link-type: doc

      **Configuration reference**
      ^^^
      The TOML-first public API of HydroModPy. Every section validated by
      ``HydroModPyConfig`` with fields, defaults, types, and the JSON
      Schema explorer.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: workflows/index
      :link-type: doc

      **Workflow families and driving modes**
      ^^^
      Overview, simulation, testbed, calibration, and comparison workflows
      (with the regional_lab profile for site-catalog campaigns), plus the
      seven driving modes (CLI TOML, JSON, Python, notebooks, and low-level
      primitives).

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: concepts/workspace-layout
      :link-type: doc

      **Workspace layout**
      ^^^
      Where HydroModPy stores inputs, caches, generated artifacts, runs, and
      reports.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: concepts/project-vs-run
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

1. :doc:`concepts/workspace-layout` explains the durable folders:
   data cache, project TOMLs, generated child configs, runs, outputs, reports,
   and gallery evidence.
2. :doc:`workflows/index` explains which operation writes to those folders:
   overview for data identity cards, simulation for one persisted run, testbed
   for controlled variants (including regional_lab profile campaigns),
   calibration for repeated candidate runs, and comparison for shared-case
   solver contrasts.
3. Topic guides such as :doc:`workflows/testbed`,
   :doc:`workflows/comparison`, and :doc:`workflows/calibration` are the
   single source of truth for each workflow family. They link out to
   theory, gallery, and architecture rather than re-describing the
   workflow walkthroughs.
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
      :link: workflows/testbed
      :link-type: doc

      **Mesh diagnostics**
      ^^^
      Mesh-only runs via simulation with ``[[simulation.process]]`` type=mesh,
      testbed-based discretization studies, refinement policies, and the
      route to mesh scientific and architecture pages.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: workflows/comparison
      :link-type: doc

      **Comparison workflows**
      ^^^
      How to run shared-case comparisons and how to read their generated
      metrics and figures.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: workflows/calibration
      :link-type: doc

      **Calibration workflows**
      ^^^
      Entry points for inverse problems, calibration architecture, and
      calibration benchmark pages.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: solvers
      :link-type: doc

      **Solvers**
      ^^^
      Process-first map of flow, transport, postprocess, and display
      solvers, with the trade-offs between MODFLOW-NWT, MODFLOW 6,
      Boussinesq, mesh families, and the XT3D option.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: modflow6-lake
      :link-type: doc

      **Lakes and reservoirs**
      ^^^
      How to declare a MODFLOW 6 LAK lake in config: geometry polygon,
      stage-volume-area abacus, bed leakance, spillway and controlled
      outlets, forcings, and where the solved stage and lake-aquifer
      exchange land.

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
      :link: catchment-report
      :link-type: doc

      **Catchment HTML reports**
      ^^^
      The ``catchment_report.toml`` contract and the standard
      ``hmp report catchment`` commands for building watershed report pages.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: project-api
      :link-type: doc

      **Project API**
      ^^^
      Python lifecycle for workspace setup, geographic preprocessing, data,
      mesh, run execution, comparison, calibration, and cleanup.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: ../theory/index
      :link-type: doc

      **Theory**
      ^^^
      Method notes, solver equations, and modelling assumptions backing each
      workflow: foundations, hydrology, mesh, calibration, and solvers.

Reading outputs
---------------

Use these pages once you have generated or opened result pages:

- :doc:`concepts/reading-results-pages` explains how to read gallery,
  comparison, and validation pages.
- :doc:`concepts/comparison-output-reading-order` gives the reading
  order for comparison artifacts.

.. toctree::
   :maxdepth: 2
   :hidden:

   Configuration reference <config_reference/index>
   Workflow families and modes <workflows/index>
   Concepts <concepts/index>
   Cookbook <cookbook/index>
   Theory <../theory/index>
   cli-reference
   Data loading <data/index>
   results-and-exports
   catalog
   figures
   catchment-report
   project-api
   solvers
   modflow6-prt
   modflow6-lake
   troubleshooting
