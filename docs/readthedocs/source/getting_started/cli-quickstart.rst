CLI quickstart
==============

After ``pip install hydromodpy`` (see :doc:`../install`), two equivalent
command-line entry points are exposed: ``hmp`` and ``hydromodpy``. They
share the same subcommands. The pages below use ``hmp`` for brevity.

.. code-block:: bash

   hmp --help              # list every subcommand
   hmp <subcommand> --help # detailed help for one subcommand

A standard first session looks like this:

.. code-block:: bash

   hmp init .                                      # scaffold this directory as a workspace
   hmp new my_basin --workspace .                  # create projects/my_basin
   hmp config template projects/my_basin/run_demo.toml --profile user
   hmp run projects/my_basin/run_demo.toml         # execute the run
   hmp list                          # browse results
   hmp show <sim_id>                 # inspect one simulation

The rest of this page explains each step.

1. Initialize a workspace
-------------------------

A workspace is a directory that owns the simulation catalog, the data
cache, and one or more projects.

.. code-block:: bash

   hmp init                          # default: ~/hydromodpy/
   hmp init /mnt/shared/hmp          # custom path
   hmp init --force                  # overwrite an existing workspace

The command creates the canonical layout:

.. code-block:: text

   <workspace>/
   |-- hydromodpy.duckdb     # simulation catalog (one per workspace)
   |-- data/                 # cached input data, one folder per variable
   |-- projects/             # one folder per project lives here
   `-- simulations/          # finalized Zarr archives and Parquet tables

See :doc:`workspace-layout` for the resolution rules and the role of
each folder.

2. Create a project
-------------------

A project bundles one catchment configuration plus one or more run
variants.

.. code-block:: bash

   hmp new my_basin                              # uses ~/hydromodpy/
   hmp new my_basin --workspace /mnt/shared/hmp  # custom workspace

The command writes ``projects/my_basin/project.toml`` (shared settings)
and ``projects/my_basin/run_demo.toml`` (executable run that inherits
from ``project.toml``). See :doc:`project-vs-run` for the inheritance
rules.

3. Generate a configuration template
------------------------------------

Use ``hmp config template`` to bootstrap a TOML file with every field
documented inline. Each line carries the type, the default, and the
constraint.

.. code-block:: bash

   hmp config template config.toml                         # all modules
   hmp config template config.toml --profile user          # minimal
   hmp config template config.toml --profile expert        # all knobs
   hmp config template config.toml --modules geographic flow modflownwt
   hmp config template --list-modules                      # available modules

The generated file is meant to be edited. Validation against the
Pydantic schema is available with:

.. code-block:: bash

   hmp config check projects/my_basin/run_demo.toml

4. Pre-fetch solver binaries (optional)
---------------------------------------

MODFLOW, MODPATH, and MT3D-USGS binaries download on first use into a
managed cache (``~/.cache/hydromodpy/bin/``). For CI, air-gapped
environments, or before handing a laptop to a teammate, fetch them
eagerly:

.. code-block:: bash

   hmp install-binaries                            # fetch everything
   hmp install-binaries --subset mf6,mfnwt         # subset only
   hmp install-binaries --bindir /opt/hmp_bin      # custom location
   hmp install-binaries --upgrade                  # force re-download

5. Run a workflow
-----------------

``hmp run`` reads the TOML, picks the workflow declared at the top
level (``workflow = "simulation"``, ``"calibration"``, ``"batch"``,
``"overview"``, or ``"mesh"``), and executes the full pipeline.

.. code-block:: bash

   hmp run projects/my_basin/run_demo.toml
   hmp run projects/my_basin/run_calibration.toml

The catalog updates after every successful run.

Prototype Python scripts belong to the developer namespace, outside the
stable ``hmp run`` reproducibility contract:

.. code-block:: bash

   hmp dev run-script projects/my_basin/prototype.py

6. Browse and inspect results
-----------------------------

The simulation catalog is queryable from the same CLI:

.. code-block:: bash

   hmp list                                    # all projects in workspace
   hmp list --project my_basin                 # all runs of one project
   hmp show <sim_id>                           # metadata, metrics, params
   hmp inspect <sim_id>                        # files, mesh, status
   hmp rank my_basin --metric nse --top 1      # top-ranked run
   hmp rank my_basin --metric nse --bottom 1   # bottom-ranked run
   hmp compare <sim_a> <sim_b>                 # side-by-side comparison
   hmp display <sim_id> <figure>               # render one figure

A ``sim_id`` accepts a unique prefix, so ``hmp show ab12`` matches the
single run starting with ``ab12``.

7. Diagnose the environment
---------------------------

Run ``hmp doctor`` when something breaks. It checks the Python version,
the heavy dependencies, the solver binaries, the workspace layout, and
the data cache.

.. code-block:: bash

   hmp doctor

The output flags missing pieces and prints the exact command needed to
fix each one (for example ``hmp install-binaries`` when a binary is
absent).

8. Run the test suite
---------------------

The test runner ships with the package:

.. code-block:: bash

   hmp test unit                       # fastest tier
   hmp test regression --fast          # reference outputs
   hmp test regression --extensive     # full coverage
   hmp test regression -j auto         # parallel
   hmp test validation --fast          # scientific benchmarks

Tier definitions and tags are documented in :doc:`../contribute`.

9. Share a simulation
---------------------

Simulation outputs can be exported from a project workspace and imported
into another workspace when packaged:

.. code-block:: bash

   hmp export projects/my_basin --sim run_demo --csv --output exports/run_demo
   hmp export projects/my_basin --sim run_demo --geotiff --resolution 100 --output exports/maps
   hmp add my_run.hmp                          # import into current dir
   hmp add my_run.hmp -w /mnt/shared/hmp       # import into a workspace
   hmp add my_run.hmp --as renamed_run         # rename on import
   hmp add my_run.hmp --dry-run                # validate without writing

The archive contains the configuration, the inputs, and the results
together. ``hmp add`` re-materializes them inside the target workspace.

Other commands
--------------

Less common but documented for reference:

.. list-table::
   :header-rows: 1
   :widths: 20 60

   * - Command
     - Purpose
   * - ``hmp delete``
     - Remove a simulation (DuckDB row plus Zarr store).
   * - ``hmp data``
     - Inspect or manage custom data artefacts in the workspace.
   * - ``hmp lock``
     - Manage the reproducible data lockfile (``hydromodpy.lock``).
   * - ``hmp report``
     - Render the HTML report for a calibration session.
   * - ``hmp schema``
     - Export the JSON Schema and companion files for frontend hooks.
   * - ``hmp completion``
     - Emit a shell completion script for bash, zsh, or fish.

Where to look next
------------------

- :doc:`workspace-layout` documents the resolution order between an
  explicit workspace path, the ``HYDROMODPY_WORKSPACE`` environment
  variable, and the default ``~/hydromodpy/`` location.
- :doc:`project-vs-run` explains the TOML inheritance contract between
  ``project.toml`` and the ``run_*.toml`` variants.
- :doc:`../seven-modes` lists the seven supported user APIs (CLI,
  TOML, Python, notebook).
- ``CONTRIBUTING.md`` (repository root) holds the deep reference for
  the configuration system, the workspace catalog schema, and the
  Pydantic field declaration rules.
