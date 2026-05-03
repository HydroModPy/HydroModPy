CLI Reference
=============

HydroModPy exposes two equivalent console entry points:

.. code-block:: bash

   hmp --help
   hydromodpy --help

The documentation uses ``hmp`` for brevity. This page lists the registered
top-level subcommands. Use ``hmp <command> --help`` for the complete argparse
reference of one command.

Command inventory
-----------------

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Command
     - Main role
     - Typical use
   * - ``hmp init``
     - Workspace setup
     - Create the catalog, data cache, projects folder, and simulation folder.
   * - ``hmp new``
     - Project scaffolding
     - Create a new project and starter TOML files inside a workspace.
   * - ``hmp config``
     - Configuration tooling
     - Generate templates, validate TOML files, list modules, or open the
       interactive configuration wizard.
   * - ``hmp schema``
     - Frontend integration
     - Export JSON Schema and companion metadata for UI integrations.
   * - ``hmp run``
     - Workflow execution
     - Execute ``simulation``, ``overview``, ``mesh``, ``calibration``,
       ``batch``, ``comparison``, or ``testbed`` TOML workflows, or run a
       Python prototype script.
   * - ``hmp display``
     - Figure rendering
     - Render registered display figures for one persisted simulation.
   * - ``hmp report``
     - Calibration reporting
     - Render the HTML report for a calibration session.
   * - ``hmp list``
     - Catalog browsing
     - List projects or runs in a workspace.
   * - ``hmp export``
     - Export
     - Export geographic data or simulation results to external formats.
   * - ``hmp test``
     - Test runner
     - Run unit, regression, validation, PETSc, or benchmark-oriented test
       subsets.
   * - ``hmp data``
     - Data-cache management
     - Inspect, validate, or register custom data artifacts.
   * - ``hmp lock``
     - Reproducibility
     - Update, verify, archive, or restore the data lockfile.
   * - ``hmp show``
     - Run summary
     - Show metadata, metrics, and parameters for a simulation.
   * - ``hmp compare``
     - Pairwise comparison
     - Compare two simulations by id, prefix, or name.
   * - ``hmp add``
     - Package import
     - Import a portable ``.hmp`` archive and dematerialize bundled inputs.
   * - ``hmp import``
     - Package import
     - Import a portable ``.hmp`` package into a workspace.
   * - ``hmp doctor``
     - Environment diagnosis
     - Check Python, dependencies, solver binaries, workspace, and data cache.
   * - ``hmp inspect``
     - Run inspection
     - Inspect metadata, mesh, status, files, and persisted artifacts.
   * - ``hmp manage``
     - Local catalog UI
     - Open a local browser UI for DuckDB tables and simulation management.
   * - ``hmp install-binaries``
     - Solver binaries
     - Download MODFLOW, MODPATH, and MT3D-USGS binaries into the managed
       HydroModPy cache.
   * - ``hmp best``
     - Ranking
     - Show the top simulation for a project ranked by one metric.
   * - ``hmp worst``
     - Ranking
     - Show the bottom simulation for a project ranked by one metric.
   * - ``hmp delete``
     - Catalog cleanup
     - Delete a simulation from DuckDB and remove its Zarr store.
   * - ``hmp completion``
     - Shell integration
     - Emit completion scripts for bash, zsh, or fish.

Workflow execution flags
------------------------

``hmp run`` accepts workflow-independent TOML files, but checkpoint and step
flags only apply to ``workflow = "simulation"``:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Flag
     - Effect
   * - ``--dry-run``
     - Print the resolved workflow, sections, and simulation pipeline steps
       without executing the run.
   * - ``--resume <run_id>``
     - Resume a simulation from the latest checkpoint for the given run id.
   * - ``--from <step>``
     - Resume from a named or indexed pipeline step.
   * - ``--until <step>``
     - Stop after a named or indexed pipeline step.
   * - ``--no-checkpoint``
     - Disable checkpoint persistence for the current simulation run.
   * - ``--frozen``
     - Reject fresh downloads when a lockfile is present; every artifact must
       already exist and match its recorded hash.
   * - ``--no-display``
     - Persist results without rendering configured display figures.

Nested command families
-----------------------

Some commands expose their own subcommands:

.. code-block:: bash

   hmp config template --help
   hmp config check --help
   hmp data list --help
   hmp lock verify --help
   hmp test validation --help

Use :doc:`../getting_started/cli-quickstart` for the first-run path and
:doc:`results-and-exports` for catalog, inspection, and export workflows.
