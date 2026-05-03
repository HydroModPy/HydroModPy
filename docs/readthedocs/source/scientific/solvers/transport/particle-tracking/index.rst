Particle Tracking Internals
===========================

This section structures the particle-tracking documentation inside the
``transport`` process.

Particle tracking answers questions such as:

- where particles move under one solved flow field;
- how long advective travel takes;
- which zones or release locations contribute to endpoints;
- how paths change when the upstream flow model changes.

Current Particle-Tracking Backend
---------------------------------

.. list-table::
   :header-rows: 1
   :widths: 28 28 44

   * - Process/solver pair
     - Backend family
     - Required upstream flow
   * - ``transport/modpath``
     - MODPATH.
     - Earlier ``flow/modflownwt`` run.

.. toctree::
   :maxdepth: 2

   modpath

Related Pages
-------------

- :doc:`../common-concepts`
- :doc:`../concentration-transport`
- :doc:`../../flow/modflow/transport-coupling`
- :doc:`../../../../architecture/solver/transport/modpath-stack`
