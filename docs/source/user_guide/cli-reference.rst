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
     - Execute ``simulation``, ``overview``, ``calibration``,
       ``comparison``, or ``testbed`` TOML workflows, or run a
       Python prototype script.
   * - ``hmp dev``
     - Developer diagnostics
     - Inspect internal configuration and workflow surfaces used during
       development.
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
   * - ``hmp export-package``
     - Export
     - Bundle a simulation as a portable ``.hmp`` archive (tar.zst with
       RO-Crate manifest).
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
     - Check Python, dependencies, solver binaries, workspace, data cache, and
       result-storage consistency.
   * - ``hmp inspect``
     - Run inspection
     - Inspect metadata, mesh, status, files, and persisted artifacts.
   * - ``hmp manage``
     - Local catalog UI
     - Open a local browser UI for DuckDB tables, result diagnostics, and
       explicit cleanup or legacy-name normalization of selected result
       artefacts.
   * - ``hmp install-binaries``
     - Solver binaries
     - Download MODFLOW, MODPATH, and MT3D-USGS binaries into the managed
       HydroModPy cache.
   * - ``hmp rank``
     - Ranking
     - Rank simulations for a project by one metric.
   * - ``hmp delete``
     - Catalog cleanup
     - Delete a simulation from DuckDB and remove its Zarr store.
   * - ``hmp workspace``
     - Workspace utilities
     - Inspect or initialize workspace paths and storage conventions.
   * - ``hmp completion``
     - Shell integration
     - Emit completion scripts for bash, zsh, or fish.
   * - ``hmp gc``
     - Maintenance
     - Garbage-collect orphan calibration sessions, geographic_cache, tmp
       parquet, and stale running simulations.
   * - ``hmp vacuum``
     - Maintenance
     - CHECKPOINT DuckDB catalogs and consolidate Zarr metadata.
   * - ``hmp privacy``
     - Data governance
     - Hard-delete a simulation and emit a JSON purge certificate.
   * - ``hmp index``
     - Cross-workspace discovery
     - Search, forget, or prune entries of the machine-wide global index.

Workflow execution flags
------------------------

``hmp run`` accepts workflow-independent TOML files, but checkpoint and step
flags only apply to ``[workflow].mode = "simulation"``:

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
   * - ``--overlay <path.toml>``
     - Merge an extra TOML payload after the ``base_config`` chain. The flag
       can be repeated; later overlays win.
   * - ``--set <path=value>``
     - Override one dotted TOML path after overlays, for example
       ``--set workspace.project_root=/tmp/run``.

Override precedence is, from lowest to highest: defaults, ``base_config``
chain, ``--overlay`` files, then ``--set`` values. The XDG-aligned
environment overrides ``HMP_CACHE_HOME``, ``HMP_STATE_HOME``, and
``HMP_BIN`` only relocate machine caches and binary directories; they
do not patch config fields.

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
