Transport Coupling
==================

This page records the current transport-coupling convention for MODFLOW-family
flow outputs.

The flow backend determines which downstream transport route is normally used:

- ``flow/modflow6`` is the preferred upstream flow path for
  ``transport/modflow6gwt``.
- ``flow/modflownwt`` is the legacy upstream flow path for
  ``transport/modpath`` and ``transport/mt3dms``.

Transport coupling should be checked after the flow outputs are already
understood. In particular, do not compare transport fields before checking:

- the groundwater-head state convention;
- the active-domain and cell-volume convention;
- period budgets and their time interval metadata;
- storage and drainage semantics;
- whether the exported velocity or flux field is a local cell quantity, a
  face quantity, or a post-processed diagnostic.

Related scientific pages:

- :doc:`../../solver-capability-matrix`
- :doc:`../../modflow-package-semantics-and-boundary-conditions`
- :doc:`../../vertical-representation-and-storage-assumptions`
