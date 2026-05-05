Streams And Seepage
===================

This section is the scientific entry point for stream supports, seepage,
drainage outflow, and simulation-derived active stream networks.

It sits beside :doc:`../hydrology/index` because these concepts are not only
forcing inputs. They are groundwater-surface exchange concepts. Some objects
are loaded or generated as geographic supports, some become solver boundary
conditions, and some are post-processed interpretations of model outputs.

The organizing idea is simple but important: do not ask "where is the river?"
before asking what role the river-like object plays in the model. A line can
be an observation, a computational support, a boundary condition, or a
diagnostic mask. Those roles should remain separate.

Recommended Reading Path
------------------------

1. Start with :doc:`conceptual-model`.
   It introduces the physical scene first, then brings in the equations and
   sketches progressively: stream boundary, seepage/drainage, simulated-active
   network.
2. Use :doc:`worked-examples` when you want examples that connect the concepts
   to commands, files, and figures that can actually be opened.
3. Use :doc:`status-and-limitations` to check what is currently supported,
   what is demonstrated by examples, and what is not yet a stable contract.
4. Use :doc:`../hydrology/stream-ocean-and-drainage-semantics` when you need
   solver-facing vocabulary for ``stream``, ``ocean``, and ``drainage``.
5. Use :doc:`../hydrology/simulated-active-network` when the question is how a
   simulated seepage or drainage field becomes an active-network view.
6. Use :doc:`nancon-k-sweep-results` and
   :doc:`network-metrics-and-extreme-k-sweep` when you want concrete results,
   figures, and comparison metrics. The latter page is the metric map:
   overlap, planar bidirectional distance, and the remaining downslope
   distance work needed to reproduce the article-style criterion.

The pages are ordered this way because the equations are meaningful only after
the modelling question is clear. A prescribed stream head, a seepage threshold,
and a post-processed active mask may occupy nearby places on the map, but they
do not have the same scientific status.

Object Roles
------------

HydroModPy separates three network roles.

``reference``
   The observed or externally loaded stream network. This is the validation
   target when comparing simulated activity to hydrography.

``generated``
   A DEM/topography-derived network. It can be useful as a geomorphological
   diagnostic or as a modelling support, but it is not an observation.

``simulated_active``
   The active network inferred from simulated drainage or seepage fields. It
   is a result interpretation, not an input network.

For scientific validation of simulated activity, the target is ``reference``.
If the run has no ``reference`` network, HydroModPy should skip the
simulated-active overlap comparison rather than silently falling back to
``generated``.

Method Roles At A Glance
------------------------

.. list-table::
   :header-rows: 1
   :widths: 24 28 25 23

   * - Role
     - Question answered
     - What exists before solve
     - What exists after solve
   * - Stream boundary
     - How much water is exchanged against a known surface head?
     - support and prescribed ``H_stream``
     - computed ``q_stream``
   * - Seepage / drainage
     - Where does groundwater emerge at the surface?
     - support and local ``z_s``
     - computed ``outflow_drain`` or ``q_seep``
   * - Simulated active network
     - Which connected network is implied by simulated emergence?
     - positive outflow field and routing graph
     - ``accumulation_flux``, mask, metrics

Examples That Carry The Explanation
-----------------------------------

The section has one dedicated example page:

- :doc:`worked-examples`
- :doc:`status-and-limitations`

Use these as the bridge between the concepts and the actual artifacts. They
explain which example is best for:

- choosing between a stream boundary and a seepage/drainage operator;
- checking the MODFLOW 6 ``outflow_drain`` to ``accumulation_flux`` path;
- reading the Nancon MODFLOW 6 K-sweep against the observed ``reference``
  network;
- using the MODFLOW-NWT Nancon basin page as a legacy baseline;
- reading comparison folders in a defensible order.

Concept Map
-----------

The map below is intentionally placed after the reading path and role table.
It is a compact implementation view, not the first explanation of the concept.

.. uml:: diagrams/stream_seepage_role_map.wsd

The important separation is:

- stream linework can be an observed object, a generated object, or a support;
- stream-style boundaries prescribe a stage/head condition;
- seepage or drainage conditions prescribe a release law controlled by
  ``h - z_s``;
- the simulated active network is computed after the groundwater solve.

.. toctree::
   :maxdepth: 2
   :hidden:

   conceptual-model
   Worked examples <worked-examples>
   Status and limitations <status-and-limitations>
   Nancon K-sweep results <nancon-k-sweep-results>
   Network metrics and extreme K-sweep <network-metrics-and-extreme-k-sweep>
   Boundary semantics <../hydrology/stream-ocean-and-drainage-semantics>
   Simulated active network <../hydrology/simulated-active-network>
