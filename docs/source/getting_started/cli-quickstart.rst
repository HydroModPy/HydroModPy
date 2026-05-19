CLI quickstart
==============

.. page-badges::
   :difficulty: beginner
   :time: 10 min

After ``pip install hydromodpy`` (see :doc:`../install`), two equivalent
command-line entry points are exposed: ``hmp`` and ``hydromodpy``. They
share the same subcommands. The pages below use ``hmp`` for brevity.

.. code-block:: bash

   hmp --help              # list every subcommand
   hmp <subcommand> --help # detailed help for one subcommand

A standard first session looks like this:

.. code-block:: bash

   hmp workspace init .                                  # scaffold this directory as a workspace
   hmp project new my_basin --workspace .                # create projects/my_basin
   hmp config template projects/my_basin/hydromodpy.toml --profile user
   hmp run projects/my_basin/hydromodpy.toml             # execute the run
   hmp catalog ls                    # browse simulation results
   hmp catalog show <sim_id>         # inspect one simulation

The rest of this page explains each step.

1. Initialize a workspace
-------------------------

A workspace is a directory that owns the simulation catalog, the data
cache, and one or more projects.

.. code-block:: bash

   hmp workspace init                          # default: ~/hydromodpy/
   hmp workspace init /mnt/shared/hmp          # custom path
   hmp workspace init --force                  # overwrite an existing workspace

The command creates the canonical layout:

.. code-block:: text

   <workspace>/
   |-- workspace.toml         # metadata of the research workspace
   |-- data/                  # cache.duckdb + cached input data (one folder per variable)
   `-- projects/              # one folder per project, each owns its catalog.duckdb

See :doc:`../user_guide/concepts/workspace-layout` for the resolution rules and the role of
each folder.

2. Create a project
-------------------

A project bundles one catchment configuration plus one or more run
variants.

.. code-block:: bash

   hmp project new my_basin                              # uses ~/hydromodpy/
   hmp project new my_basin --workspace /mnt/shared/hmp  # custom workspace

The command writes ``projects/my_basin/hydromodpy.toml`` (the project
config validated by ``HydroModPyConfig``) and an empty
``projects/my_basin/catalog.duckdb`` deployed via the v2 migration
runner. See :doc:`../user_guide/concepts/project-vs-run` for the
project / run distinction.

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
   hmp install-binaries --mf6-prt                  # mf6 for MODFLOW 6 PRT
   hmp install-binaries --bindir /opt/hmp_bin      # custom location
   hmp install-binaries --upgrade                  # force re-download

5. Run a workflow
-----------------

``hmp run`` reads the TOML, picks the workflow declared at the top
level (``[workflow].mode = "simulation"``, ``"overview"``, ``"testbed"``,
``"calibration"``, or ``"comparison"``), and executes the full pipeline.

.. code-block:: bash

   hmp run projects/my_basin/hydromodpy.toml
   hmp run projects/my_basin/calibration_run.toml

The catalog updates after every successful run.

Prototype Python scripts belong to the developer namespace, outside the
stable ``hmp run`` reproducibility contract:

.. code-block:: bash

   hmp dev run-script projects/my_basin/prototype.py

6. Browse and inspect results
-----------------------------

The simulation catalog is queryable from the same CLI:

.. code-block:: bash

   hmp catalog ls                              # all runs in the workspace
   hmp catalog query "SELECT name, solver FROM simulations LIMIT 5"
   hmp catalog show <sim_id>                   # metadata, metrics, params
   hmp catalog show <sim_id> --detail          # files, mesh, status, Zarr groups
   hmp rank --metric nse --top 1               # top-ranked run in project
   hmp rank --metric nse --bottom 1            # bottom-ranked run in project
   hmp compare <sim_a> <sim_b>                 # side-by-side comparison
   hmp viz show <sim_id> <figure>              # render one figure
   hmp viz gallery <config.toml>               # render the [display] gallery

A ``sim_id`` accepts a unique prefix, so ``hmp catalog show ab12`` matches
the single run starting with ``ab12``.

7. Diagnose the environment
---------------------------

Run ``hmp doctor`` when something breaks. It checks the Python version,
the heavy dependencies, the solver binaries, the workspace layout, and
the data/result caches.

.. code-block:: bash

   hmp doctor

The output flags missing pieces and prints the exact command needed to
fix each one (for example ``hmp install-binaries`` when a binary is
absent). When a project catalog is present, it also reports result-storage
drift such as completed catalog rows without Zarr artefacts, orphan
Zarr/Parquet artefacts, and leftover ``*.parquet.tmp`` files.

8. Share a simulation
---------------------

Package one run as a single archive that another workspace can import:

.. code-block:: bash

   hmp export projects/my_basin --sim run_demo --output exports/run_demo
   hmp add exports/run_demo.hmp

The archive bundles the configuration, the inputs, and the results.
``hmp add`` re-materializes them inside the target workspace.

For the full set of commands (the ``project``, ``catalog``, ``workspace``,
``viz``, ``audit``, and ``privacy`` families, plus ``data``, ``lock``,
``manage``, ``report``, ``schema``, ``completion``, and every flag of the
verbs shown above), see :doc:`../user_guide/cli-reference`.

Where to look next
------------------

- :doc:`../user_guide/concepts/workspace-layout` documents the
  workspace > project > run hierarchy and the resolution rules.
- :doc:`../user_guide/concepts/project-vs-run` explains the project
  vs run distinction and the ``hydromodpy.toml`` contract.
- :doc:`../user_guide/workflows/index` lists the seven supported
  user APIs (CLI, TOML, Python, notebook).
- :doc:`../user_guide/config_reference/index` is the deep reference for
  the configuration system, the workspace catalog schema, and the
  Pydantic field declaration rules.
