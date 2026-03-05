Data Definition And Transfer Activity
=====================================

Scope
-----

This diagram documents the control flow that defines active data families and
transfers concrete data objects to the right runtime holders.

It focuses on:

- planning-time activation (`DataManagersPlanner.build`),
- setup-time geology transfer to `Domain`,
- data-phase transfer of hydrometry to launcher loaded-data state,
- continuation into simulation execution after data placement is complete.

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
- Hydrometry transfer is implemented by `DataManagersRuntimeLoader` during `_run_data()`.
- Missing/invalid hydrometry configuration can be downgraded to warnings in
  `data.inference_mode = "warn"` mode.
