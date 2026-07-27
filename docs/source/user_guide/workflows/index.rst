Workflow Reference
==================

HydroModPy distinguishes two orthogonal questions and answers them with two
different vocabularies. Mixing them is the most common source of confusion
when reading the docs and the code.

- A **workflow** answers *what user-facing operation does this run perform?*
  The value lives in ``[workflow].mode`` at the top of every TOML.
- A **mode** answers *how is HydroModPy driven for that workflow?*
  CLI, Python facade, JSON payload, notebook, or low-level primitives.

The same workflow can run through several modes. The ``simulation`` workflow,
for example, can be launched from a CLI TOML, from a Python script that
loads the same TOML, from a notebook with lazy phase reload, or from a
frontend that posts a JSON payload.

Choose a workflow
-----------------

The mandatory ``[workflow].mode`` field selects the user-facing operation.

.. code-block:: toml

   [workflow]
   mode = "simulation"

.. list-table::
   :header-rows: 1
   :widths: 14 30 28 28

   * - Workflow
     - Use it to
     - Main TOML sections
     - Detailed page
   * - ``overview``
     - Inspect a watershed and available data before solving.
     - ``[workspace]``, ``[geographic]``, ``[domain]``, ``[data]``,
       ``[overview]``
     - :doc:`overview`
   * - ``simulation``
     - Run one forward model and persist one run.
     - ``[simulation]``, ``[[simulation.process]]``, ``[flow]``,
       ``[solver]``, backend sections
     - :doc:`simulation`
   * - ``testbed``
     - Expand controlled method variants and collect evidence, including mesh
       resolution, constraint studies, and regional campaigns.
     - ``[testbed]``, ``[testbed.runner]``, ``[[testbed.variant]]``,
       child-runner sections such as ``[simulation]`` or ``[comparison]``.
       Set ``[testbed].profile = "regional_lab"`` for site-catalog campaigns.
     - :doc:`testbed`, :doc:`regional_lab`
   * - ``site_selection``
     - Build and review a selected catchment catalog before regional-lab or
       simulation runs.
     - ``[site_selection]``, optional ``[hydrometry]``, ``[data]``
     - :doc:`site_selection`
   * - ``calibration``
     - Estimate parameters by running repeated candidate simulations.
     - ``[calibration]``, ``[calibration.parameters.*]``, simulation
       sections
     - :doc:`calibration`
   * - ``comparison``
     - Generate several child simulations from one shared base case and
       compare observables.
     - ``[comparison]``, ``[[comparison.simulation]]``,
       ``[[comparison.observable]]``
     - :doc:`comparison`

Workflow dispatch table
-----------------------

Click any entry to jump to its detailed page.

.. list-table:: ``hmp run`` dispatch by ``workflow.mode``
   :header-rows: 1
   :widths: 22 78

   * - ``workflow.mode``
     - Launcher and dedicated page
   * - ``overview``
     - :doc:`overview`
   * - ``simulation``
     - :doc:`simulation`
   * - ``testbed``
     - :doc:`testbed` (use ``[testbed].profile = "regional_lab"`` for the
       :doc:`regional_lab` profile)
   * - ``calibration``
     - :doc:`calibration`
   * - ``comparison``
     - :doc:`comparison`
   * - ``site_selection``
     - :doc:`site_selection`

Dispatch model
--------------

The CLI dispatch is intentionally simple:

.. code-block:: text

   hmp run <config.toml>
        |
        +-- read [workflow].mode = "..."
        |
        +-- dispatch to one launcher
              simulation  -> Project(config).simulate()
              overview    -> DataOverviewLauncher
              testbed     -> TestbedLauncher (or regional_lab profile)
              calibration -> calibration ask/tell loop
              comparison  -> SimulationComparisonLauncher

This split avoids mixing three concepts:

- a workflow is the operation requested by the user;
- a solver is one numerical backend used by some workflows;
- a usage mode is the interface used to drive the operation.

Choosing a workflow
-------------------

Use ``overview`` when the model domain itself is still uncertain. It is the
best workflow for data availability, watershed identity cards, observation
inventories, and pre-solver QA.

Use ``simulation`` when the physical setup is clear and you want one forward
run with persisted model outputs.

Use ``testbed`` when the question is about robustness across method variants,
for example mesh resolution, mesh constraints, hydraulic-parameter sensitivity,
or future transport method axes. Mesh testbeds use ``subject = "mesh"`` with
``runner.type = "simulation"``; the generated children are normal simulation
TOMLs that declare ``[[simulation.process]]`` with ``type = "mesh"``. For
site-catalog campaigns over many basins or clusters, use ``testbed`` with
``[testbed].profile = "regional_lab"``. See :doc:`regional_lab`.

Use ``site_selection`` when the question is upstream of model generation: which
gauged or candidate basins should enter a campaign, which outlets delineate
plausible watersheds, and which sites should be exported as a reviewed
``regional_lab_sites.csv`` catalog.

Use ``calibration`` when parameters are uncertain and the goal is to optimize
or sample them against observations or synthetic targets.

Use ``comparison`` when several child simulations must stay tied to one shared
physical base case so that solver, mesh, or option differences remain
controlled.

Mesh-only runs are not a separate workflow. Express them as
``[workflow].mode = "simulation"`` with a ``[[simulation.process]]`` block
whose ``type = "mesh"``.

Choose a mode
-------------

The mode is the entry interface used to drive the chosen workflow.

.. list-table::
   :header-rows: 1
   :widths: 4 28 32 36

   * - Mode
     - Use case
     - Entry point
     - Reference file
   * - 1
     - Reproducible run from a config file
     - ``hmp run <file>.toml``
     - ``examples/projects/02_nancon_watershed/run_transient_nwt.toml``
   * - 2
     - Frontend or external tool
     - ``Project(payload)``
     - ``hydromodpy/schema/`` JSON exports
   * - 3
     - Multiple runs sharing one base TOML
     - ``Project("project.toml")`` plus a Python loop
     - ``examples/projects/02_nancon_watershed/run_sweep_sy.toml``
   * - 4
     - Python API with a validated config
     - ``HydroModPyConfig.from_toml(...)``
     - ``examples/projects/02_nancon_watershed/run_full_python.py``
   * - 5
     - Step-by-step debug run
     - ``project.build_geographic/load_data/build_mesh/simulate``
     - ``examples/projects/02_nancon_watershed/run_transient_prototype.py``
   * - 6
     - Notebook with phase reload
     - ``Project(cfg)``
     - ``examples/projects/02_nancon_watershed/run_cellular.py``
   * - 7
     - Primitive objects without ``Project``
     - ``CatchmentDelineation``, ``Domain``, ...
     - any helper script

Why TOML-first
--------------

The CLI plus a TOML config is the recommended path for reproducible studies,
shared cases, and CI. The TOML stays the canonical source of truth: the
Pydantic root ``HydroModPyConfig`` validates it, the JSON Schema export
keeps frontends in sync, and the calibration cache fingerprints rely on
the resolved tree.

Python modes (3 to 7) are prototyping paths. They are useful for sweeps,
debugging, custom analysis loops, and notebook exploration, but a published
result should always trace back to a TOML that ``hmp run`` can replay.

Modes in detail
---------------

Mode 1. CLI TOML
~~~~~~~~~~~~~~~~

A full TOML drives ``hmp run``. The recommended mode for shared and
reproducible work.

.. code-block:: bash

   hmp run examples/projects/02_nancon_watershed/run_transient_nwt.toml

The TOML declares workspace, catchment, domain, data sources, flow process,
and the simulation block. Inheritance through ``base_config`` keeps a
shared project file separated from per-run overlays.

Mode 2. JSON payload
~~~~~~~~~~~~~~~~~~~~

External frontends submit a JSON payload validated by the same Pydantic
schema as the TOML loader.

.. code-block:: python

   import hydromodpy as hmp

   project = hmp.Project(payload)
   project.simulate()

JSON Schema definitions live under ``hydromodpy/schema/`` and are kept in
sync with the Pydantic models.

Mode 3. TOML plus Python orchestration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A TOML owns the model state. Python loops over a parameter and launches one
run per value. Useful for sweeps and sensitivity studies before moving to
mode 4.

.. code-block:: python

   import hydromodpy as hmp

   project = hmp.Project("examples/projects/02_nancon_watershed/project.toml")
   for sy in [0.01, 0.05, 0.3]:
       project.simulate(Sy=sy, name=f"sy_{sy}")

Mode 4. Python API
~~~~~~~~~~~~~~~~~~

The TOML remains the source of truth. Python loads the resolved Pydantic
model, holds it in memory, and hands it to ``Project``.

.. code-block:: python

   from pathlib import Path
   import hydromodpy as hmp
   from hydromodpy.config import HydroModPyConfig

   cfg = HydroModPyConfig.from_toml(Path("run_transient_nwt.toml"))
   hmp.Project(cfg).simulate()

Mode 5. Step by step
~~~~~~~~~~~~~~~~~~~~

The model phase can be driven one verb at a time. Useful for debugging,
inspecting intermediate state, or inserting custom code between two phases.

.. code-block:: python

   project.build_geographic()
   project.load_data()
   project.build_mesh()
   project.simulate(K=5e-5)

Mode 6. Cellular notebook
~~~~~~~~~~~~~~~~~~~~~~~~~

Lazy construction lets a notebook re-run only the phase that changed. The
geographic runtime and the data loading run once. The mesh build and the
simulation can iterate without re-downloading data.

.. code-block:: python

   project = hmp.Project(cfg)
   project.build_geographic()  # slow, runs once
   project.load_data()         # slow, runs once
   project.build_mesh()
   project.simulate()

Mode 7. Primitive objects
~~~~~~~~~~~~~~~~~~~~~~~~~

Use the underlying primitives without a :class:`~hydromodpy.project.Project`
facade. Useful for unit tests, one-off geographic preprocessing, or
embedding a single component in another workflow.

.. code-block:: python

   from hydromodpy.spatial.geographic import CatchmentDelineation
   from hydromodpy.spatial.domain import Domain
   from hydromodpy.spatial.mesh import HydroMesh
   from hydromodpy.physics.flow import Flow

The data managers under ``hydromodpy.data`` can also be called directly to
fetch a single source (BRGM geology, BD TOPAGE hydrography, Hub'Eau
piezometry, SIM2 climate, etc.).

Read more
---------

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: CLI reference
      :link: ../cli-reference
      :link-type: doc

      Registered ``hmp`` subcommands, workflow flags, and override
      precedence.

   .. grid-item-card:: Project API
      :link: ../project-api
      :link-type: doc

      Python lifecycle for setup, data, mesh, run, comparison, and
      calibration.

   .. grid-item-card:: Configuration reference
      :link: ../config_reference/index
      :link-type: doc

      Every TOML field validated by ``HydroModPyConfig``, with defaults,
      types, and the JSON Schema explorer.

   .. grid-item-card:: Workspace layout
      :link: ../concepts/workspace-layout
      :link-type: doc

      Where projects, runs, caches, and catalogs live on disk.

.. toctree::
   :maxdepth: 2

   overview
   simulation
   testbed
   regional_lab
   site_selection
   calibration
   comparison
