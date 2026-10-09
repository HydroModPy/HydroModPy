Mental model and design choices
===============================

This page explains why HydroModPy is split into several layers instead of
collapsing everything into one execution object. Use it when the question is not
only "what is this object?" but also "why does this boundary exist?". The page
ends with the files to open first for each kind of change.

At a glance
-----------

The main execution path is:

.. code-block:: text

   TOML
   -> workflow
   -> Project
   -> SimulationPlanner
   -> SimulationPlan (ProcessRun...)
   -> Pipeline
   -> SimulationRunner
   -> SolverAdapter
   -> concrete solver
   -> Catalog
   -> Run

The main input-data path is:

.. code-block:: text

   TOML
   -> DataLoadPlan
   -> Variable
   -> Manager
   -> Source
   -> DataCatalogDuckDB

The first path answers:
"how does a configuration become a persisted result?"

The second path answers:
"where do the input data come from, and how are they cached?"

Overview diagram
----------------

The diagram below is the compact visual version of those two paths.

.. uml:: diagrams/overview_toml_to_run_components.wsd

What this diagram explains:

- the user-facing entry points,
- the separation between planning and execution,
- the parallel input-data path,
- the difference between persistence and later result reading.

What it intentionally simplifies:

- the internal pipeline steps,
- the detailed process runtime payloads,
- backend-specific solver internals,
- post-processing detail after ingestion.

Why so many layers?
-------------------

The short answer is: different parts of the system evolve at different
speeds.

- TOML contracts evolve with user workflows and frontend needs.
- Planners and pipelines evolve with orchestration needs.
- Solver integrations evolve with backend-specific constraints.
- Input data sources evolve with APIs, formats, and preprocessing rules.
- Result reading evolves with post-processing and comparison workflows.

If these concerns all live in one place, small changes propagate too far.
The current split tries to reduce that coupling.

Why ``Project`` exists
----------------------

``Project`` is the user-facing facade.

It exists to provide:

- one simple Python entry point,
- one common language across CLI, scripts, and notebooks,
- one place that composes planning, execution, and persistence.

Without this facade, most users would need to directly manipulate lower
level objects that exist for orchestration, not for ergonomic use.

Three distinctions that matter
------------------------------

``workflow`` vs ``SimulationPlan`` vs ``Pipeline``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

These three concepts answer different questions:

- ``workflow``: which user-facing mode was requested?
- ``SimulationPlan``: which execution units must run, and in what logical
  order?
- ``Pipeline``: how does the technical execution advance, step by step?

This separation matters because it prevents the CLI contract from being
tightly bound to one specific internal implementation.

``ProcessRun`` vs ``Run``
^^^^^^^^^^^^^^^^^^^^^^^^^

``ProcessRun`` is a planned execution unit before runtime.

``Run`` is a read handle over a persisted simulation result.

Keeping these separate avoids ambiguity between:

- something that still has to be executed,
- something that has already been written and can be queried again.

``Catalog`` vs ``DataCatalogDuckDB``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

HydroModPy keeps two persistent memories because they do not have the same
lifecycle:

- ``DataCatalogDuckDB`` caches input data that may be reused by many runs.
- ``Catalog`` tracks outputs that belong to particular runs.

The important relation between them is provenance, not identity.

Another distinction worth preserving
------------------------------------

``Variable``, ``Manager``, and ``Source`` also solve different problems:

- ``Variable``: what kind of scientific data is needed?
- ``Manager``: what loading policy should be applied?
- ``Source``: where does the concrete data come from?

This lets HydroModPy change a provider without renaming the scientific
concept, or change the loading policy without changing the source contract.

Hydrographic network naming
---------------------------

The hydrographic-network work is a good example of why HydroModPy keeps
separate concepts for:

- loaded input data,
- generated geographic products,
- persisted run features,
- downstream display and comparison views.

The canonical persisted names are now:

- ``hydrographic_network_reference`` for the network loaded from
  ``data.hydrography``
- ``hydrographic_network_reference_permanent`` for the reaches of that network
  that flow all year, when the loader can tell them
- ``hydrographic_network_generated`` for the network derived from
  ``geographic.river_network``

The feature-store contract keeps only the canonical names. Historical filenames
may still exist on disk, but they are not feature aliases:

- ``river_network.shp`` remains the generated-network vector filename.
- ``river_network_summary.json`` remains the generated-network summary
  filename.
- ``streams.shp`` remains the reference vector filename, and
  ``streams_permanent.shp`` the permanent reaches beside it.
- ``hydrography_streams`` is the canonical reference forcing-raster name.

This split is intentional. A manager may still write a historical filename on
disk, while the runtime and comparison layers rely on the canonical feature
names to avoid ambiguity.

Hydrographic network class structure
------------------------------------

The hydrographic-network stack is intentionally split across several classes
because they do not answer the same question.

.. uml:: spatial_support/diagrams/hydrographic_network_class_map.wsd

The key distinction is:

- ``HydrographicNetwork`` is the canonical cross-layer concept for one network.
- ``HydrographicNetworks`` is only a bundle of available roles for one site/run.
- ``HydrographicNetworkComparison`` is the result of comparing two networks.
- ``RiverNetworkProducts`` remains the technical output bundle of the
  ``geographic.river_network`` preprocessing step.

Put differently:

- one loaded reference network becomes ``HydrographicNetwork(role="reference")``
- one DEM-derived network becomes ``HydrographicNetwork(role="generated")``
- the roles are ``reference``, ``reference_permanent``, ``generated``,
  ``mesh_constraint`` and ``simulated_active``
- the preprocessing code may still first emit ``RiverNetworkProducts``
- the runtime then groups available roles in ``HydrographicNetworks``
- the ``Run`` facade exposes reading and comparison operations over the
  persisted networks

This is why HydroModPy does not use one "god object" for hydrographic
networks. It keeps:

- one class for the canonical concept,
- one class for the role bundle,
- one class for the comparison result,
- one technical class for the low-level generated artifacts.

The display layer stays separate. Figures consume the canonical networks and
comparison payloads, but rendering is not embedded in the data classes
themselves.

The simulated active network
----------------------------

The hydrographic-network contract reserves a third role, ``simulated_active``,
for the network that emerges from simulated drainage. It exists in the type
contract (``HydrographicNetworks.simulated_active``) and no workflow step stores
it as a vector feature. What HydroModPy computes from the persisted
``accumulation_flux`` field are lazy views of the run: ``run.drainage_density()``,
``run.persistence()``, ``run.cell_field_active_mask()``,
``run.cell_field_active_metrics()``, ``run.cell_field_network_overlap_metrics()``
and ``run.cell_field_network_distance_metrics()``, and the figures
``simulated_active_network`` and ``simulated_active_network_reference_overlay``.
They live in ``hydromodpy.results.derive.views`` and read fields, mesh geometry
and the stored roles without changing the catalog.
:doc:`spatial_support/hydrographic-network-simulated-active-inventory` states
what each view returns.

Where to start reading
----------------------

For a package, open its README: ``hydromodpy/<package>/README.md`` holds the
parts, the import rules and a "where to add what" table, and the same text is
the page of :doc:`packages/index`. For a path through the code, start here.

**One TOML to solver outputs**

1. ``hydromodpy/cli/commands/run.py``, then ``hydromodpy/_api.py`` (``run``) and
   ``hydromodpy/project/dispatch/workflow.py``;
2. ``hydromodpy/project/facade.py`` (``Project``);
3. ``hydromodpy/simulation/planning/planner.py``;
4. ``hydromodpy/simulation/execution/runner.py``;
5. ``hydromodpy/solver/base/registry.py``;
6. one adapter under ``hydromodpy/solver/<backend>/adapters/``;
7. the backend package under ``hydromodpy/solver/``.

**A runtime mesh**

1. ``hydromodpy/spatial/mesh/launcher/runtime.py``;
2. ``hydromodpy/spatial/mesh/model/hydro_mesh.py`` (``HydroMesh``);
3. ``hydromodpy/spatial/mesh/launcher/batch.py`` for several outlets;
4. ``hydromodpy/spatial/mesh/gmsh_grid/``;
5. the pages of :doc:`mesh/index`.

**A calibration**

1. ``hydromodpy/calibration/runners/cli_runner.py``;
2. ``hydromodpy/calibration/optim/engine.py``;
3. ``hydromodpy/calibration/runners/trial.py``, the prepare-once and
   evaluate-many primitive;
4. the pages of :doc:`calibration/index`.

**Where backend-specific logic starts**

1. ``hydromodpy/solver/modflow_common/flow_adapter_helpers.py``, the lifecycle
   shared by the MODFLOW adapters;
2. ``hydromodpy/solver/modflow6/adapters/flow.py`` or
   ``hydromodpy/solver/modflow_nwt/adapters/flow.py``;
3. ``hydromodpy/solver/modflow_common/`` for the shared MODFLOW code;
4. ``hydromodpy/solver/boussinesq/`` for the in-house backend.

Next
----

- :doc:`layered-architecture` for the import rules between packages.
- :doc:`data-scopes` for the three databases.
- :doc:`simulation/toml-to-solver-walkthrough` for the same path with the objects
  named.
- :doc:`spatial_support/hydrographic-network-uml-diagrams`.
