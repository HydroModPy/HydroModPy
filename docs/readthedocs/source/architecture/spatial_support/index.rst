Spatial Support Architecture
============================

This section documents how HydroModPy defines spatial zones/supports and how
they are consumed by ``Field`` and ``FieldParam`` during heterogeneous
parameter mapping.

Use it when you want:

- the support-definition contract owned by ``hydromodpy.spatial.domain``,
- the runtime path from support config to registered support objects,
- the choice between geology-backed, synthetic, and catchment-backed zonings.

.. toctree::
   :maxdepth: 2

   support-selection-guide
   spatial-support-uml-diagrams
