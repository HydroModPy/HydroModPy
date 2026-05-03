Streams And Seepage
===================

This section is the scientific entry point for stream supports, seepage,
drainage outflow, and simulation-derived active stream networks.

It sits beside :doc:`../hydrology/index` because these concepts are not only
forcing inputs. They are groundwater-surface exchange concepts: some are loaded
or generated as network supports, some are solver boundary conditions, and some
are post-processed outputs.

Use this section when the question is:

- what is the difference between a stream boundary and seepage?
- where do observed and DEM-derived stream networks enter the model?
- what does the solver prescribe, and what does it compute?
- how does local seepage or drainage outflow become an active-network view?
- what can be compared with the observed ``reference`` network?

Reading Map
-----------

.. list-table::
   :header-rows: 1
   :widths: 24 46 30

   * - Question
     - Read
     - Main objects
   * - I need the concepts before the implementation.
     - :doc:`conceptual-model`
     - stream support, seepage support, active mask
   * - What is ``stream`` versus ``drainage``?
     - :doc:`../hydrology/stream-ocean-and-drainage-semantics`
     - ``stream``, ``ocean``, ``drainage``
   * - How does simulated seepage become an active network?
     - :doc:`../hydrology/simulated-active-network`
     - ``outflow_drain``, ``accumulation_flux``
   * - What exists in the code and what is still missing?
     - :doc:`../../architecture/overview/hydrographic-network-simulated-active-inventory`
     - ``simulated_active`` computed views
   * - Which comparison files should be opened after a run?
     - :doc:`../../getting_started/comparison-workflow`
     - ``simulated_active_network_*.csv``

Conceptual Roles
----------------

HydroModPy separates three network roles.

- ``reference`` is the observed or externally loaded stream network.
- ``generated`` is the DEM/topography-derived network.
- ``simulated_active`` is the active network inferred from simulated drainage
  or seepage fields.

For scientific validation of simulated activity, the target is
``reference``. If the run has no ``reference`` network, HydroModPy should skip
the simulated-active overlap comparison rather than silently falling back to
``generated``. The ``generated`` network can still be useful as a separate
geomorphological diagnostic, but it is not an observation.

Core Diagram
------------

.. uml:: diagrams/stream_seepage_role_map.wsd

The diagram above is the high-level map. The important separation is:

- stream linework can be an observed object, a generated object, or a support;
- stream-style boundaries prescribe a stage/head condition;
- seepage or drainage conditions prescribe a release law;
- the simulated active network is computed after the groundwater solve.

.. toctree::
   :maxdepth: 2
   :hidden:

   conceptual-model
   Boundary semantics <../hydrology/stream-ocean-and-drainage-semantics>
   Simulated active network <../hydrology/simulated-active-network>
