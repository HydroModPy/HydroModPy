Workspace Layout
================

HydroModPy organises every project around a single **workspace** directory.
The workspace is the only place where simulation results, input data cache,
and project configurations live. There is exactly one simulation catalog per
workspace.

Canonical layout
----------------

.. code-block:: text

   <workspace>/
   ├── hydromodpy.duckdb              # simulation catalog (shared across projects)
   ├── data/
   │   ├── cache.duckdb               # input data cache only
   │   └── <variable>/                # raw files (CSV, NC, TIF)
   ├── simulations/
   │   └── <uuid>.zarr/               # one Zarr per run (physical isolation)
   └── projects/
       ├── my_basin/
       │   ├── project.toml
       │   └── run_demo.toml
       └── another_project/
           └── project.toml

Scaffold a workspace with ``hmp init``:

.. code-block:: bash

   hmp init ~/hmp_workspace
   hmp new my_basin --workspace ~/hmp_workspace

Workspace resolution
--------------------

HydroModPy v1 uses a **strict binary resolver**. Given a project TOML,
it answers "where is the workspace" by trying three branches in order:

1. **Explicit** (in the TOML)

   .. code-block:: toml

      [workspace]
      root = "/path/to/workspace"
      # or any combination of per-component overrides:
      # catalog_path = "/path/to/hydromodpy.duckdb"
      # data_dir = "/path/to/data"
      # simulations_dir = "/path/to/simulations"

2. **Env var** - ``HYDROMODPY_WORKSPACE`` pointing at a directory.

3. **Scaffold** - the TOML lives at
   ``<workspace>/projects/<name>/project.toml`` and ``<workspace>`` contains
   a ``hydromodpy.duckdb`` file or a ``data/`` directory.

Anything else raises :class:`~hydromodpy.core.workspace.WorkspaceError`
with an actionable hint listing the three options. There is no walk-up
auto-discovery and no silent fallback to ``project_root``.

Diagnose resolution
-------------------

``hmp doctor`` reports which branch produced the workspace and lists the
four resolved paths:

.. code-block:: bash

   hmp doctor --toml ~/hmp_workspace/projects/my_basin/project.toml

Sample output:

.. code-block:: text

   OK     workspace            resolved via scaffold
   OK     workspace_root       /home/bb/hmp_workspace
   OK     catalog_path         /home/bb/hmp_workspace/hydromodpy.duckdb
   OK     data_dir             /home/bb/hmp_workspace/data
   OK     simulations_dir      /home/bb/hmp_workspace/simulations

When the TOML cannot be resolved, ``hmp doctor`` surfaces the exact
``WorkspaceError`` message that ``hmp run`` would raise.
