Data Definition And Transfer Activity
=====================================

Scope
-----

This diagram documents the control flow that defines active data families and
transfers concrete data objects to the right runtime holders.

It focuses on:

- planning-time activation (`DataPlanner.build`),
- setup-time geology transfer to `Domain`,
- data-phase transfer of hydrometry to the ``Project`` runtime
  loaded-data state,
- continuation into simulation execution after data placement is
  complete.

Code map
--------

- ``hydromodpy/data/planner.py``:
  activation inference before execution starts.
- ``hydromodpy/data/runtime_loader.py``:
  concrete data-loading dispatch during the runtime phase.
- ``hydromodpy/project.py``:
  orchestration of ``setup_workspace`` / ``build_geographic`` /
  ``load_data``.
- ``hydromodpy/physics/flow/structure_binders.py``:
  example of downstream consumers that expect transferred structures.

Recommended reading path
------------------------

1. ``hydromodpy/data/planner.py``
2. ``hydromodpy/project.py``
3. ``hydromodpy/data/runtime_loader.py``
4. one bound family such as ``hydromodpy/data/variables/geology/`` or
   ``hydromodpy/data/variables/hydrometry/``

Diagram source
--------------

.. uml:: diagrams/data_definition_transfer_activity.wsd

.. literalinclude:: diagrams/data_definition_transfer_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - data definition and transfer activity

Notes
-----

- The same raw TOML can influence both activation inference and data payloads.
- Geology transfer is driven by resolved data types at setup time.
- Hydrometry transfer is implemented by `DataManagersRuntimeLoader`
  during ``Project.load_data()``.
- Missing or invalid hydrometry configuration can be downgraded to
  warnings in `data.inference_mode = "warn"` mode.

Related diagrams
----------------

- :doc:`data-definition-transfer-class-diagram`
- :doc:`../simulation/simulation-orchestration-class-diagram`
