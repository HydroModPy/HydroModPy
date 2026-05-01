Seven ways to drive HydroModPy
==============================

HydroModPy exposes a single :class:`~hydromodpy.Project` facade and seven
supported usage modes. Every mode feeds the same pipeline. Only the
construction layer differs. Pick the mode that matches your workflow:
TOML for reproducible runs, Python for prototyping, notebook cells for
exploration.

The reference example projects under
``examples/projects/02_nancon_watershed/`` provide one concrete file for
each mode. The list below points to those files.

Quick comparison
----------------

.. list-table::
   :header-rows: 1
   :widths: 6 30 30 34

   * - Mode
     - Use case
     - Entry point
     - Reference file
   * - 1
     - Reproducible run from a config file
     - ``hmp run <file>.toml``
     - ``run_transient_nwt.toml``
   * - 2
     - Frontend or external tool
     - ``Project.from_json(payload)``
     - ``schema/`` JSON exports
   * - 3
     - Multiple runs sharing one base TOML
     - ``Project("project.toml")``
     - ``run_sweep_sy.toml``
   * - 4
     - Python API with validated config
     - ``HydroModPyConfig.from_toml(...)``
     - ``run_full_python.py``
   * - 5
     - Step-by-step debug run
     - ``project.prepare/execute/...``
     - ``run_transient_prototype.py``
   * - 6
     - Notebook with phase reload
     - ``Project.lazy(cfg)``
     - ``run_cellular.py``
   * - 7
     - Primitive objects without ``Project``
     - ``CatchmentDelineation``, ``Domain``, ...
     - any helper script

Mode 1. CLI TOML
----------------

A full TOML file drives ``hmp run``. This is the recommended mode for
reproducible simulations and for sharing a run with collaborators.

.. code-block:: bash

   hmp run examples/projects/02_nancon_watershed/run_transient_nwt.toml

The TOML file declares the workspace, the catchment, the domain, the
data sources, the flow process, and the simulation block. See
``examples/projects/02_nancon_watershed/project.toml`` for a base
configuration and ``run_transient_nwt.toml`` for a transient run that
inherits it through ``base_config``.

Mode 2. Frontend with JSON
--------------------------

External frontends (web UI, Streamlit, REST) send a JSON payload that
Pydantic validates against the same schema as the TOML files.

.. code-block:: python

   import hydromodpy as hmp

   project = hmp.Project.from_json(payload)
   project.run()

JSON Schema definitions live under ``hydromodpy/schema/``. They are
generated from the same Pydantic models used by the TOML loader, so the
two interfaces stay in sync.

Mode 3. TOML + Python orchestration
-----------------------------------

A TOML file owns the model state. Python loops over a parameter and
launches one run per value. Useful for sweeps, sensitivity studies, and
calibration scaffolds before moving to Mode 4.

.. code-block:: python

   import hydromodpy as hmp

   project = hmp.Project("examples/projects/02_nancon_watershed/project.toml")
   for sy in [0.01, 0.05, 0.3]:
       project.run(Sy=sy, name=f"sy_{sy}")

The companion file
``examples/projects/02_nancon_watershed/run_sweep_sy.toml`` is kept as a
design draft for a future TOML sweep workflow. It is not accepted by
``hmp run`` in v1.

Mode 4. Python API
------------------

The TOML file remains the reproducible source of truth. Python code can
load the resolved Pydantic model, keep it in memory, and hand it to
``Project``.

.. code-block:: python

   from pathlib import Path
   import hydromodpy as hmp
   from hydromodpy.master_config.hydromodpy_config import HydroModPyConfig

   HERE = Path(__file__).parent
   cfg = HydroModPyConfig.from_toml(HERE / "run_transient_nwt.toml")
   hmp.Project(cfg).run()

The reference file is
``examples/projects/02_nancon_watershed/run_full_python.py``.

Mode 5. Step-by-step
--------------------

The pipeline can be driven one verb at a time. Useful for debugging, for
inspecting intermediate state, or for inserting custom Python between
two phases.

.. code-block:: python

   sim_id = project.prepare(K=5e-5)
   project.execute(sim_id)
   project.ingest(sim_id)
   project.render(sim_id)
   project.cleanup(sim_id)

See ``run_transient_prototype.py`` in the nancon example.

Mode 6. Cellular notebook
-------------------------

Lazy construction lets a notebook re-run only the phase that changed.
The geographic preprocessing and the data loading run once. The mesh
build and the simulation can iterate without re-downloading data.

.. code-block:: python

   project = hmp.Project.lazy(cfg)
   project.build_geographic()  # slow, runs once
   project.load_data()         # slow, runs once
   project.build_mesh()

The reference file is ``run_cellular.py`` in the nancon example.

Mode 7. Primitive objects
-------------------------

Use the underlying primitives without a :class:`~hydromodpy.Project`
facade. Useful for unit tests, for one-off geographic preprocessing, or
for embedding a single component in another workflow.

.. code-block:: python

   from hydromodpy.spatial.geographic import CatchmentDelineation
   from hydromodpy.spatial.domain import Domain
   from hydromodpy.spatial.mesh import HydroMesh
   from hydromodpy.physics.process import Flow

The data managers under ``hydromodpy.data`` can also be called directly
to fetch a single source (BRGM geology, BD TOPAGE hydrography, Hub'Eau
piezometry, SIM2 climate, ...).

Showcase: all data APIs in one run
----------------------------------

The file
``examples/projects/02_nancon_watershed/run_overview_all_apis.toml``
runs every public data source through Mode 1. Use it as a smoke test
when you want to confirm that an environment can reach all the APIs
HydroModPy supports (BRGM 1:1M and 1:50k geology, BD TOPAGE / EU-Hydro /
OSM hydrography, Hub'Eau piezometry, SIM2 climate, etc.).
