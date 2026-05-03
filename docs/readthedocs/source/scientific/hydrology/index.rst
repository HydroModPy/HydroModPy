Hydrology And Forcing
=====================

This section documents the hydrological side of HydroModPy that prepares or
transfers climatic and recharge-related information toward groundwater-flow
solvers.

It is the right place for:

- recharge-generation narratives,
- PyHELP coupling notes,
- runoff, evapotranspiration, and climatic forcing chains,
- semantic distinctions between recharge, runoff, ETP, and surface exchange,
- unit-conversion and time-aggregation conventions.

If you are looking for stream networks, seepage, drainage outflow, or
simulation-derived active streams, use the sibling section
:doc:`../streams_and_seepage/index`. For a concrete run with figures and
metrics, see :doc:`../streams_and_seepage/nancon-k-sweep-results`.

.. toctree::
   :maxdepth: 2

   hydrological-forcing-chain
   forcing-time-aggregation-and-first-clim
   recharge-and-surface-exchange-semantics
