Particle Tracking
=================

Particle tracking answers questions about advective travel paths and travel
times through a previously solved flow field.

Current Solver
--------------

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Solver
     - Requires
     - Role
   * - ``modpath``
     - Earlier ``flow/modflownwt`` run.
     - Tracks particles using the MODFLOW-NWT flow model as the velocity
       source.

Typical Plan
------------

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflownwt"]

   [[simulation.process]]
   id = "transport_main"
   type = "transport"
   solvers = ["modpath"]

Typical Parameters
------------------

.. code-block:: toml

   [transport.modpath.parameters]
   zone_partic = "domain"
   track_dir = "forward"
   cell_div = 2
   zloc_div = false

Scientific Reading Notes
------------------------

- Interpret MODPATH outputs as downstream products of the selected flow model.
- A change in the upstream ``flow/modflownwt`` mesh, boundary conditions, or
  recharge forcing changes the particle result.
- Do not compare particle paths across flow solvers without documenting the
  upstream support and flow-field differences.

Related Pages
-------------

- :doc:`../flow/modflow-family`
- :doc:`../../../architecture/solver/transport/modflow-transport-adapters`
- :doc:`../solver-capability-matrix`
