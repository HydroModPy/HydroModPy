Mental Model & Design Choices
=============================

This page explains why HydroModPy is split into several layers instead of
collapsing everything into one execution object.

Use it when the question is not only "what is this object?" but also
"why does this boundary exist?".

The repository also contains a developer glossary under
``docs/developers/glossary.md`` for shorter term-by-term definitions.

For package-by-package reading guidance, use :doc:`code-reading-guide`.

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
   -> SolverRunner
   -> concrete solver
   -> SimulationCatalog
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

.. literalinclude:: diagrams/overview_toml_to_run_components.wsd
   :language: text
   :caption: PlantUML (.wsd) source - overview TOML to Run component diagram

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

Why `Project` exists
--------------------

`Project` is the user-facing facade.

It exists to provide:

- one simple Python entry point,
- one common language across CLI, scripts, and notebooks,
- one place that composes planning, execution, and persistence.

Without this facade, most users would need to directly manipulate lower
level objects that exist for orchestration, not for ergonomic use.

Three distinctions that matter
------------------------------

`workflow` vs `SimulationPlan` vs `Pipeline`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

These three concepts answer different questions:

- `workflow`: which user-facing mode was requested?
- `SimulationPlan`: which execution units must run, and in what logical
  order?
- `Pipeline`: how does the technical execution advance, step by step?

This separation matters because it prevents the CLI contract from being
tightly bound to one specific internal implementation.

`ProcessRun` vs `Run`
^^^^^^^^^^^^^^^^^^^^^

`ProcessRun` is a planned execution unit before runtime.

`Run` is a read handle over a persisted simulation result.

Keeping these separate avoids ambiguity between:

- something that still has to be executed,
- something that has already been written and can be queried again.

`SimulationCatalog` vs `DataCatalogDuckDB`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

HydroModPy keeps two persistent memories because they do not have the same
lifecycle:

- `DataCatalogDuckDB` caches input data that may be reused by many runs.
- `SimulationCatalog` tracks outputs that belong to particular runs.

The important relation between them is provenance, not identity.

Another distinction worth preserving
------------------------------------

`Variable`, `Manager`, and `Source` also solve different problems:

- `Variable`: what kind of scientific data is needed?
- `Manager`: what loading policy should be applied?
- `Source`: where does the concrete data come from?

This lets HydroModPy change a provider without renaming the scientific
concept, or change the loading policy without changing the source contract.

Hydrographic Network Naming
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
- ``hydrographic_network_generated`` for the network derived from
  ``geographic.river_network``

Older names are still present as compatibility aliases, but they should not be
used as the conceptual center anymore:

- ``river_network`` is the legacy generated-feature alias
- ``streams.shp`` is the legacy reference vector filename
- ``hydrography_streams`` is the legacy forcing-raster name

This split is intentional. A manager may still write a historical filename on
disk, while the runtime and comparison layers rely on the canonical feature
names to avoid ambiguity.

Hydrographic Network Class Structure
------------------------------------

The hydrographic-network stack is intentionally split across several classes
because they do not answer the same question.

.. uml:: diagrams/hydrographic_network_class_map.wsd

.. literalinclude:: diagrams/hydrographic_network_class_map.wsd
   :language: text
   :caption: PlantUML (.wsd) source - hydrographic-network class responsibilities

The key distinction is:

- ``HydrographicNetwork`` is the canonical cross-layer concept for one network.
- ``HydrographicNetworks`` is only a bundle of available roles for one site/run.
- ``HydrographicNetworkComparison`` is the result of comparing two networks.
- ``RiverNetworkProducts`` remains the technical output bundle of the
  ``geographic.river_network`` preprocessing step.

Put differently:

- one loaded reference network becomes ``HydrographicNetwork(role="reference")``
- one DEM-derived network becomes ``HydrographicNetwork(role="generated")``
- the preprocessing code may still first emit ``RiverNetworkProducts``
- the runtime then groups available roles in ``HydrographicNetworks``
- the ``Run`` facade exposes reading and comparison operations over the
  persisted networks

This is why HydroModPy does not use one "god object" for hydrographic
networks. It keeps:

- one class for the canonical concept,
- one class for the role bundle,
- one class for the comparison result,
- one legacy-compatible class for the low-level generated artifacts.

The display layer stays separate. Figures consume the canonical networks and
comparison payloads, but rendering is not embedded in the data classes
themselves.

Diagrams worth adding
---------------------

Not every UML diagram is worth the maintenance cost. The highest-value
diagrams for this part of HydroModPy would be:

1. A component diagram for ``TOML -> Run``.
2. A sequence diagram for one nominal execution.
3. A facade-object relationship diagram for `Workspace`, `Project`,
   `SimulationCatalog`, `Run`, and `SimulationGroup`.
4. A data-loading diagram for `Variable -> Manager -> Source -> cache`.
5. A simple identifier map for `sim_id`, `simulation.run_id`, and
   `ProcessRun.id`.

The last one is especially valuable because identifier confusion is hard to
fix with prose alone.

Where to go next
----------------

- :doc:`hydrographic-network-uml-diagrams`
- :doc:`code-reading-guide`
- :doc:`two-databases`
- :doc:`../simulation/toml-to-solver-walkthrough`
