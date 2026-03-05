Data Definition And Transfer Activity
=====================================

Scope
-----

This diagram documents the control flow that defines active data families and
transfers concrete data objects to the right runtime holders.

It focuses on:

- planning-time activation (`DataManagersPlanner.build`),
- setup-time geology transfer to `Domain`,
- data-phase hook transfer of hydrometry to `RunResult`,
- continuation into simulation execution after data placement is complete.

Diagram source
--------------

.. uml:: diagrams/data_definition_transfer_activity.wsd

.. literalinclude:: diagrams/data_definition_transfer_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - data definition and transfer activity

Notes
-----

- The same raw TOML can influence both activation inference and hook payloads.
- Geology transfer is driven by resolved data types at setup time.
- Hydrometry transfer is implemented in `on_after_data` when that hook exists.
- Missing/invalid hydrometry configuration is handled as a non-fatal branch in
  the example hook (`result.hydrometry = None`).
