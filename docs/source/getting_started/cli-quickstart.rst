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

A standard first session:

.. code-block:: bash

   hmp workspace init .                              # scaffold this directory
   hmp project new my_basin --workspace .            # create projects/my_basin
   hmp run projects/my_basin/run_demo.toml           # execute the run
   hmp catalog ls                                    # browse the results
   hmp catalog show demo --detail                    # inspect one run

The rest of this page explains each step.

1. Initialize a workspace
-------------------------

A workspace owns the shared input-data cache and hosts one or more
projects.

.. code-block:: bash

   hmp workspace init                          # default: ~/hydromodpy/
   hmp workspace init /mnt/shared/hmp          # custom path
   hmp workspace init . --force                # overwrite an existing workspace

The command creates:

.. code-block:: text

   <workspace>/
   ├── workspace.toml         name, contact, licence, geographic scope
   ├── data/                  one folder per variable, with a README and examples
   └── projects/
       └── example/           a ready-to-run synthetic demo project

Each ``data/<variable>/`` ships a README and one example file per accepted
format, so you can copy the naming convention for your own files. The
``cache.duckdb`` index appears in ``data/`` on the first run.

See :doc:`../user_guide/concepts/workspace-layout` for the resolution rules
and the role of each folder.

2. Create a project
-------------------

A project bundles one catchment configuration plus one or more run
variants.

.. code-block:: bash

   hmp project new my_basin                              # uses ~/hydromodpy/
   hmp project new my_basin --workspace /mnt/shared/hmp  # custom workspace

It writes three files under ``projects/my_basin/``:

- ``project.toml``, the shared settings. It is also the marker that anchors
  the project root.
- ``run_demo.toml``, an executable run inheriting from it through
  ``base_config = "project.toml"``.
- ``.gitignore``, which excludes the generated ``runs/``, ``sessions/``,
  ``share/`` and ``.hmp/``.

No database is created at that point. See
:doc:`../user_guide/concepts/project-vs-run` for the project / run
distinction.

3. Edit or generate a configuration
-----------------------------------

The scaffolded ``project.toml`` and ``run_demo.toml`` are meant to be
edited. To discover the fields available in a section, generate a
documented template into a **separate** file:

.. code-block:: bash

   hmp config template template.toml                       # every module
   hmp config template template.toml --profile user        # user-facing fields only
   hmp config template template.toml --profile expert      # every knob
   hmp config template template.toml --modules geographic flow modflownwt
   hmp config template --list-modules                      # available modules

Each generated line carries the type, the default and the constraint. The
template is a field catalogue to copy from, not a runnable config: it has no
``[workspace].project_root``, so validating it reports what is still
missing. Validate the real config instead:

.. code-block:: bash

   hmp config check projects/my_basin/run_demo.toml

There is also an interactive path, ``hmp config wizard <output.toml>``.

4. Pre-fetch solver binaries (optional)
---------------------------------------

MODFLOW, MODPATH and MT3D-USGS binaries download on first use into a
managed cache (``~/.cache/hydromodpy/bin/``). For CI, air-gapped
environments, or before handing a laptop to a teammate, fetch them
eagerly:

.. code-block:: bash

   hmp install-binaries                            # fetch everything
   hmp install-binaries --subset mf6,mfnwt         # subset only
   hmp install-binaries --mf6-prt                  # mf6 build with the PRT model
   hmp install-binaries --bindir /opt/hmp_bin      # custom location
   hmp install-binaries --upgrade                  # force re-download

5. Run a workflow
-----------------

``hmp run`` reads the TOML, picks the workflow declared at the top level
(``[workflow].mode = "simulation"``, ``"overview"``, ``"calibration"``,
``"comparison"``, ``"testbed"`` or ``"site_selection"``), and executes the
pipeline.

.. code-block:: bash

   hmp run projects/my_basin/run_demo.toml
   hmp run projects/my_basin/run_demo.toml --dry-run   # print the steps, run nothing

``--dry-run`` prints the resolved workflow, the sections it found and the
numbered pipeline steps. See :doc:`/cli/run` for the resume, overlay and
override flags.

The run lands in ``projects/my_basin/runs/<name>/``, named after
``[simulation].name``. Launching an unchanged config again is a no-op:
HydroModPy reports ``Config identical to completed run``. Add ``--force``
to run it anyway; the result is versioned as ``<name>.v2``.

Prototype Python scripts stay outside the ``hmp run`` reproducibility
contract:

.. code-block:: bash

   hmp dev run-script projects/my_basin/prototype.py

6. Browse and inspect results
-----------------------------

.. code-block:: bash

   hmp catalog ls                                  # every run of the project
   hmp catalog ls --status completed --solver modflow6
   hmp catalog show demo                           # metadata, metrics, parameters
   hmp catalog show demo --detail                  # plus the Zarr store layout
   hmp catalog diff demo demo.v2                   # only the keys that differ
   hmp catalog query "SELECT name, solver, status FROM v_simulation_summary"
   hmp report compare demo demo.v2                 # side-by-side metric table
   hmp viz show demo piezometric_map               # render one figure
   hmp viz list                                    # every registered figure name

A run is addressed by name, by versioned name (``demo.v2``), by unique id
prefix, or by selector (``@last``, ``@last~1``, ``@best:nse``,
``@worst:rmse``, ``@running``).

Query the ``v_simulation_summary`` view rather than the ``simulations``
table: the table stores foreign keys (``solver_id``, ``status_id``), the
view resolves them into readable columns.

7. Rebuild the index
--------------------

The DuckDB file in ``.hmp/`` is an index over the run directories, not the
source of truth.

.. code-block:: bash

   hmp catalog reindex

It walks ``runs/`` and ``sessions/``, reads each ``manifest.json`` and
``session.json``, and repopulates every table. Use it after moving a
project, after restoring a backup, or whenever ``hmp doctor`` reports that
the index row count and the run directory count disagree.

8. Diagnose the environment
---------------------------

.. code-block:: bash

   hmp doctor
   hmp doctor --toml projects/my_basin/run_demo.toml

``hmp doctor`` checks the Python version, the heavy dependencies, the solver
binaries, and prints the exact command needed to fix each gap (for example
``hmp install-binaries``). With ``--toml`` it also reports how the workspace
was resolved, the resolved paths, and whether the index matches the run
directories on disk.

9. Share a run
--------------

.. code-block:: bash

   hmp catalog export demo -o share/demo.hmp
   hmp catalog import share/demo.hmp

The ``.hmp`` archive bundles the frozen configuration, the provenance, the
fields and the tables, with checksums verified on import. To export a single
variable in a GIS or ParaView format instead, use ``hmp data export``; see
:doc:`../user_guide/results-and-exports`.

For the full command surface, see :doc:`/cli/index`.

Where to look next
------------------

- :doc:`../user_guide/concepts/workspace-layout` documents the
  workspace > project > run hierarchy and the resolution rules.
- :doc:`../user_guide/concepts/project-vs-run` explains the project
  vs run distinction and the ``project.toml`` contract.
- :doc:`../user_guide/results-and-exports` answers "where are my outputs".
- :doc:`../user_guide/workflows/index` lists the supported workflow modes.
- :doc:`../user_guide/config_reference/index` is the deep reference for the
  configuration system and the Pydantic field declaration rules.
