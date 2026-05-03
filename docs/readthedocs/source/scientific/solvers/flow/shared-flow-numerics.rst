Shared Flow Numerics
====================

This page groups flow-solver notes that are not specific to a single backend
family.

They describe the common numerical support that determines whether two flow
simulations are scientifically comparable: mesh topology, discretization
strategy, vertical representation, parameter transfer, and mesh acceptance.

Reading Order
-------------

.. toctree::
   :maxdepth: 1

   ../meshes-and-numerical-methods
   ../mesh-and-discretization-strategies
   ../field-to-cell-parameter-transfer
   ../vertical-representation-and-storage-assumptions
   ../mesh-quality-and-acceptance-criteria

How To Use This Group
---------------------

Use these notes before interpreting solver differences. A mismatch between
``modflow6`` and ``boussinesq`` can come from the solver equations, but it can
also come from:

- different mesh topology,
- different cell areas or elevations,
- different vertical storage assumptions,
- different transfer of ``FieldParam`` records to solver cells,
- different treatment of boundary-condition geometry.

For method comparisons, document these support choices before attributing a
difference to the solver family itself.

Related Pages
-------------

- :doc:`modflow-family`
- :doc:`boussinesq-family`
- :doc:`../solver-capability-matrix`
