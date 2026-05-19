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
   * - ``hmp workspace``
     - Workspace lifecycle
     - ``init`` scaffolds a workspace, ``list`` enumerates registered
       workspaces, ``clean`` removes generated artefacts.
   * - ``hmp project``
     - Project lifecycle
     - ``new``, ``list``, ``show``, ``delete`` (the last requires
       ``--force`` outside a TTY).
   * - ``hmp catalog``
     - Catalog browsing and maintenance
     - ``ls``, ``query "<SQL>"``, ``show <sim_id> [--detail]``,
       ``gc``, ``vacuum``, ``delete``.
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
       ``comparison``, or ``testbed`` TOML workflows.
   * - ``hmp calibrate``
     - Calibration shortcut
     - Top-level wrapper around ``hmp.calibrate(<toml>)``.
   * - ``hmp dev``
     - Developer diagnostics
     - Inspect internal configuration and workflow surfaces used during
       development.
   * - ``hmp viz``
     - Figure rendering and UI
     - ``show <sim_ref> <figure>``, ``gallery <config.toml>``, and
       ``serve`` (Streamlit configuration UI).
   * - ``hmp report``
     - Calibration reporting
     - Render the HTML report for a calibration session.
   * - ``hmp data``
     - Workspace data cache and ``.hmp`` package exchange
     - ``ls``, ``get``, ``check``, ``add``, ``remove``, ``prune``,
       ``archive``, ``restore``, ``export``, ``export-package``,
       ``import``.
   * - ``hmp test``
     - Test runner
     - Run unit, regression, validation, PETSc, or benchmark-oriented test
       subsets.
   * - ``hmp doctor``
     - Environment diagnosis
     - Check Python, dependencies, solver binaries, workspace, data cache, and
       result-storage consistency. Also exposed as ``hmp dev doctor``.
   * - ``hmp install-binaries``
     - Solver binaries
     - Download MODFLOW, MODPATH, and MT3D-USGS binaries into the managed
       HydroModPy cache. Use ``--mf6-prt`` when you only need the MODFLOW 6
       executable that contains the PRT model.
   * - ``hmp privacy``
     - Data governance
     - ``purge`` deletes a simulation with a signed certificate.
       ``verify`` validates an existing certificate.
   * - ``hmp audit``
     - Workspace audit log
     - ``list`` prints recent events. ``verify`` replays the hash chain
       (placeholder until the chain is wired).
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
