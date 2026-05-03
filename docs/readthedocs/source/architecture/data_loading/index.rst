Data Loading Architecture
=========================

This section documents how the project and runtime layers define
which data families must be active and where concrete data objects are
stored for downstream use.

Use it when you want:

- the split between planning-time activation and runtime loading,
- the transfer points between loaded data, domain objects, and the
  ``Project`` runtime state,
- the code-level path from ``[data]`` config to consumed runtime
  payloads.

For user-facing guidance on choosing providers, writing source blocks, using
custom files, and locking cached data, read :doc:`../../user_guide/data/index`
first. This architecture section is for contributors who need the planner and
runtime handoff.

.. toctree::
   :maxdepth: 2

   data-definition-transfer-class-diagram
   data-definition-transfer-activity-diagram
