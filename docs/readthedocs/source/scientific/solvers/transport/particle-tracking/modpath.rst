MODPATH Particle Tracking
=========================

This page groups scientific reading for ``transport/modpath``.

Use this path when the study asks for advective trajectories or travel-time
diagnostics on top of a previous ``flow/modflownwt`` run.

What Is Repeated From The Common Transport Part
-----------------------------------------------

``transport/modpath`` still uses the common transport contract:

- it must be declared after a compatible ``flow`` process;
- it consumes an upstream flow model rather than solving groundwater flow
  itself;
- changes in upstream mesh, recharge, boundary conditions, or stress periods
  change the particle-tracking result;
- outputs must be interpreted as downstream diagnostics of a specific flow
  state.

MODPATH Specifics
-----------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Topic
     - MODPATH interpretation
   * - Process pair
     - ``transport/modpath``.
   * - Required upstream flow
     - ``flow/modflownwt``.
   * - Transport type
     - Particle tracking, not concentration transport.
   * - Main outputs
     - Pathlines and endpoints ingested into the result/catalog layer.
   * - Injection support
     - Controlled by particle-zone and particle-density parameters.
   * - Direction
     - Forward, backward, or custom tracking direction depending on config.

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

Parameter Block
---------------

.. code-block:: toml

   [transport.modpath.parameters]
   zone_partic = "domain"
   track_dir = "forward"
   cell_div = 2
   zloc_div = false

Current parameter family:

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Parameter
     - Meaning
   * - ``zone_partic``
     - Particle injection zone selector such as ``domain``,
       ``seepage_clip``, or a raster path.
   * - ``track_dir``
     - Tracking direction: ``forward``, ``backward``, or ``custom``.
   * - ``bore_depth``
     - Optional bore-depth list for vertical particle injection.
   * - ``cell_div``
     - Number of particles per axis in each cell.
   * - ``zloc_div``
     - Whether vertical subdivision is applied for particle injection.
   * - ``sel_random``
     - Optional random downsampling count of injected particles.
   * - ``sel_slice``
     - Optional slicing step for injected particles.

Interpretation Checklist
------------------------

Before comparing MODPATH outputs, document:

- upstream MODFLOW-NWT run identifier;
- grid support and stress periods;
- particle zone;
- tracking direction;
- particle density and optional downsampling;
- whether endpoints, pathlines, or derived metrics are being compared.

Related Architecture
--------------------

- :doc:`../../../../architecture/solver/transport/modpath-stack`
- :doc:`../../../../architecture/solver/transport/modflow-transport-adapters`
