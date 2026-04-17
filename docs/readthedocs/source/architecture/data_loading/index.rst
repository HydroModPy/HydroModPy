Data Loading Architecture
=========================

This section documents how launcher/runtime layers define which data families
must be active and where concrete data objects are stored for downstream use.

Use it when you want:

- the split between planning-time activation and runtime loading,
- the transfer points between loaded data, domain objects, and launcher state,
- the code-level path from ``[data]`` config to consumed runtime payloads.

.. toctree::
   :maxdepth: 2

   data-definition-transfer-class-diagram
   data-definition-transfer-activity-diagram
