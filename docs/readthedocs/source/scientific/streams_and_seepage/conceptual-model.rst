Conceptual Model
================

Purpose
-------

This page is intentionally didactic. It uses schematic diagrams only, not
simulation results. The goal is to make the vocabulary usable before reading
solver-specific pages.

The central distinction is:

- ``stream`` usually means a network support with a prescribed stage or head;
- ``seepage`` or ``drainage`` means a head-dependent release condition;
- ``simulated_active`` means a post-processed interpretation of simulated
  outflow, not an input network.

Method Sketches
---------------

The combined cross-section has been split into three method sketches. Read
them independently first: each sketch isolates one modeling question and one
kind of model object.

Stream Boundary
^^^^^^^^^^^^^^^

.. figure:: /_static/concepts/streams_and_seepage/method_stream_stage_boundary.png
   :alt: Didactic stream boundary sketch showing prescribed stage or head and computed exchange flux
   :width: 100%

   A stream-style method starts from a support and a prescribed stage/head.
   The exchange flux is returned by the solver; it is not a prescribed runoff
   input.

Seepage / Drainage
^^^^^^^^^^^^^^^^^^

.. figure:: /_static/concepts/streams_and_seepage/method_seepage_drainage_operator.png
   :alt: Didactic seepage and drainage sketch showing conditional release controlled by solved head
   :width: 100%

   A seepage or drainage method starts from a support, conductance, and
   activation level. Outflow is produced only where the solved head activates
   the release condition.

Simulated Active Network
^^^^^^^^^^^^^^^^^^^^^^^^

.. figure:: /_static/concepts/streams_and_seepage/method_simulated_active_postprocess.png
   :alt: Didactic simulated active network sketch showing postprocessed routed drainage outflow
   :width: 100%

   The simulated active network is not a boundary condition. It is a diagnostic
   built after the solve from local positive drainage outflow and a routing or
   accumulation rule.

Boundary Versus Seepage Operator
--------------------------------

.. uml:: diagrams/boundary_vs_seepage_operator.wsd

Read this diagram left to right:

1. A stream-style exchange starts from a support and a known stage/head.
2. A seepage/drainage exchange starts from a support, conductance, and
   activation threshold.
3. In both cases, the exchanged flux is a solver result, not an observed runoff
   time series.

From Seepage To Active Network
------------------------------

.. uml:: diagrams/active_network_decision_tree.wsd

This decision tree is useful when reading results.

- If the question is water balance, use ``outflow_drain``.
- If the question is active stream structure, use ``accumulation_flux`` or a
  mask derived from it.
- If the question is validation against observed hydrography, compare the mask
  with ``reference`` linework.
- If the question is a persisted vector stream network, define the threshold,
  timestep/window, and vectorization rule first. HydroModPy does not silently
  invent that canonical vector role.

Common Mistakes
---------------

Avoid these interpretations:

- ``stream`` does not currently mean full surface-water routing.
- ``seepage`` is not diffuse recharge in reverse.
- ``outflow_drain`` is not the same object as a river line.
- ``accumulation_flux`` should not be summed as a water-budget term.
- ``simulated_active`` is not a measured network unless it is explicitly
  compared with ``reference``.

Related Reading
---------------

- :doc:`../hydrology/stream-ocean-and-drainage-semantics`
- :doc:`../hydrology/simulated-active-network`
- :doc:`../../architecture/overview/hydrographic-network-simulated-active-inventory`
