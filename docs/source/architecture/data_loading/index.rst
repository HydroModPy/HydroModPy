Data Loading Architecture
=========================

This section documents how the project and runtime layers decide which
data families must be active and where concrete data objects are
stored for downstream use.

Open it when you want:

- the split between planning-time activation and runtime loading;
- the transfer points between loaded data, domain objects, and the
  ``Project`` runtime state;
- the code path from ``[data]`` config to consumed runtime payloads.

Code map
--------

- ``hydromodpy/data/planner.py`` and ``plan.py``: activation
  inference and immutable plan creation.
- ``hydromodpy/data/runtime_loader.py``: data-family dispatch during
  ``Project.load_data()``.
- ``hydromodpy/data/data_managers.py``: loaded-data container
  published to runtime state.
- ``hydromodpy/project.py``: orchestration of ``setup_workspace`` /
  ``build_geographic`` / ``load_data``.
- ``hydromodpy/physics/flow/structure_binders.py``: example downstream
  consumer that expects transferred structures.

Recommended reading path
------------------------

1. ``hydromodpy/data/data_managers_config.py``
2. ``hydromodpy/data/planner.py``
3. ``hydromodpy/data/runtime_loader.py``
4. ``hydromodpy/project.py``
5. one bound family such as ``hydromodpy/data/variables/geology/`` or
   ``hydromodpy/data/variables/hydrometry/``

Class diagram: definition and transfer
--------------------------------------

This static view documents the collaboration that defines which data
must be prepared, then transfers those data objects to the runtime
state where they are consumed.

It focuses on:

- data-type inference and normalization (``DataPlanner`` ->
  ``DataLoadPlan``);
- transfer of resolved data types into the project runtime state;
- setup-time transfer for geology (``GeologyField`` ->
  ``Domain.set_zone``);
- data-phase transfer for hydrometry (``StationSet`` ->
  ``Project.loaded_data.hydrometry``).

.. uml:: diagrams/data_definition_transfer_class.wsd

.. literalinclude:: diagrams/data_definition_transfer_class.wsd
   :language: text
   :caption: PlantUML (.wsd) source - data definition and transfer class diagram

Notes:

- ``DataLoadPlan`` defines **which** data families are active.
- ``_run_setup``, ``DataManagersRuntimeLoader``, and binders define
  **where** corresponding objects are stored.
- Geology is transferred into ``Domain`` as a zone used by process
  solvers.
- Hydrometry is transferred into the ``Project`` loaded-data state
  for diagnostics and downstream use.

Activity diagram: definition and transfer
-----------------------------------------

This control-flow view documents the activation of data families and
the transfer of concrete data objects to the right runtime holders.

It focuses on:

- planning-time activation (``DataPlanner.build``);
- setup-time geology transfer to ``Domain``;
- data-phase transfer of hydrometry to the ``Project`` runtime
  loaded-data state;
- continuation into simulation execution after data placement is
  complete.

.. uml:: diagrams/data_definition_transfer_activity.wsd

.. literalinclude:: diagrams/data_definition_transfer_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - data definition and transfer activity diagram

Notes:

- The same raw TOML can influence both activation inference and data
  payloads.
- Geology transfer is driven by resolved data types at setup time.
- Hydrometry transfer is implemented by
  ``DataManagersRuntimeLoader`` during ``Project.load_data()``.
- Missing or invalid hydrometry configuration can be downgraded to
  warnings in ``data.inference_mode = "warn"`` mode.

Related pages
-------------

- :doc:`../overview/data-managers-and-external-dependencies` for the
  external-dependency policy of every data manager.
- :doc:`../simulation/simulation-orchestration-class-diagram` for the
  simulation-side consumer of the data layer.
