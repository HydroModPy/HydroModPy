Hydrology and Forcing
=====================

.. raw:: html

   <p class="lead">
   How HydroModPy prepares and transfers climatic and recharge-related
   information toward the groundwater-flow solvers: recharge generation,
   PyHELP coupling, time aggregation, and the semantics of surface
   exchange.
   </p>

.. admonition:: Streams and seepage live next door
   :class: tip

   If you are looking for stream networks, simulated active streams,
   seepage, or drainage outflow, go to :doc:`/theory/streams_and_seepage/index`
   instead. The hydrology pages here focus on forcing chains; the streams
   section focuses on what the model returns at the surface.

Topic pages
-----------

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card:: Hydrological forcing chain
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: hydrological-forcing-chain
      :link-type: doc

      End-to-end view of how climatic inputs become recharge and
      runoff terms consumed by the flow solver.

   .. grid-item-card:: Forcing time aggregation
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: forcing-time-aggregation-and-first-clim
      :link-type: doc

      How daily, monthly, and stress-period scales are reconciled
      before the solver sees them. Includes the first-clim convention.

   .. grid-item-card:: Recharge and surface exchange semantics
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: recharge-and-surface-exchange-semantics
      :link-type: doc

      Distinction between recharge, runoff, ETP, and boundary
      exchange. How the same physical signal can be routed via
      different package paths.

   .. grid-item-card:: Stream, ocean, and drainage semantics
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: stream-ocean-and-drainage-semantics
      :link-type: doc

      Boundary conditions at the groundwater interface: how rivers,
      oceans, and drainage outlets are represented across backends.

   .. grid-item-card:: Simulated active network
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: simulated-active-network
      :link-type: doc

      Post-solve diagnostic: how stored drainage fluxes are
      thresholded into a spatial network for comparison with
      observed hydrography.

See also
--------

- :doc:`/theory/foundations/groundwater-flow-problem-definition` for the
  governing equation that consumes the forcings described here.
- :doc:`/user_guide/data/index` for the operational data managers that
  retrieve and cache these forcings.

.. toctree::
   :hidden:
   :maxdepth: 1

   hydrological-forcing-chain
   forcing-time-aggregation-and-first-clim
   recharge-and-surface-exchange-semantics
   stream-ocean-and-drainage-semantics
   simulated-active-network
