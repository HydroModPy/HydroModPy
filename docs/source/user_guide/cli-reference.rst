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
     - Workspace scaffold shortcut
     - Compatibility alias for ``hmp workspace init``.
   * - ``hmp workspace``
     - Workspace lifecycle and global-index registration
     - ``init`` scaffolds a workspace, ``list`` enumerates registered
       workspaces, ``register``/``forget``/``prune`` manage the global
       index, ``search`` runs a full-text query across registered
       workspaces, ``clean`` removes generated artefacts.
   * - ``hmp project``
     - Project lifecycle
     - ``new``, ``list``, ``show``, ``delete`` (the last requires
       ``--force`` outside a TTY).
   * - ``hmp catalog``
     - Catalog browsing and maintenance
     - ``ls``, ``query "<SQL>"``, ``show <sim_id> [--detail]``,
       ``gc``, ``vacuum``, ``delete``.
   * - ``hmp run``
     - Workflow execution
     - Execute ``simulation``, ``overview``, ``calibration``,
       ``comparison``, ``testbed``, or ``site_selection`` TOML workflows.
   * - ``hmp calibrate``
     - Calibration shortcut
     - Top-level wrapper around ``hmp.calibrate(<toml>)``.
   * - ``hmp dev``
     - Developer diagnostics and tooling
     - ``config`` generates templates or validates TOML files, ``schema``
       exports JSON Schema and companion metadata for UI integrations,
       ``doctor``, ``lock``, ``rank``, ``manage``, ``completion``, and
       ``run-script`` cover the remaining developer surfaces.
   * - ``hmp viz``
     - Figure rendering and UI
     - ``show <sim_ref> <figure>``, ``gallery <config.toml>``, and
       ``serve`` (Streamlit configuration UI).
   * - ``hmp report``
     - Reporting
     - ``render`` builds a calibration-session HTML report, ``compare``
       prints a pairwise metric comparison, and ``catchment`` builds a
       watershed HTML report from ``catchment_report.toml``.
   * - ``hmp site-selection``
     - Site-selection workflows
     - Validate, plan, and apply upstream basin site-selection configurations.
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
   * - ``--no-parallel``
     - Force sequential execution of cohort runs. Parallel cohort execution is
       enabled by default when the workflow declares multiple independent runs.
       Use this flag for debugging, deterministic step ordering, single-CPU
       environments, or when parallel I/O contention is observed.
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

   hmp dev config template --help
   hmp dev config check --help
   hmp dev schema export --help
   hmp data list --help
   hmp report catchment --help
   hmp dev lock verify --help
   hmp site-selection plan --help
   hmp test validation --help

Use :doc:`../getting_started/cli-quickstart` for the first-run path and
:doc:`results-and-exports` for catalog, inspection, and export workflows.
Use :doc:`catchment-report` for the ``catchment_report.toml`` contract.
