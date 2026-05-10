Spatial Support and Hydrography
===============================

.. raw:: html

   <p class="lead">
   How HydroModPy defines spatial zones and supports, how they are
   consumed by ``Field`` and ``FieldParam`` during heterogeneous
   parameter mapping, and how hydrography drives stream supports and
   simulated active-network diagnostics.
   </p>

Use it when you want the support-definition contract owned by
``hydromodpy.spatial.domain``, the runtime path from support config
to registered support objects, the choice between geology-backed,
synthetic, and catchment-backed zonings, or the inventory of
hydrography-derived diagnostics exposed by a persisted run.

Pages
-----

.. grid:: 1 2 2 2
   :gutter: 2 2 3 3

   .. grid-item-card:: Support selection guide
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: support-selection-guide
      :link-type: doc

      Decision matrix for picking between geology-backed,
      synthetic, and catchment-backed supports, with TOML examples
      and field-mapping consequences.

   .. grid-item-card:: Spatial support UML diagrams
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: spatial-support-uml-diagrams
      :link-type: doc

      Class and sequence diagrams for the spatial domain, support
      registry, and runtime binding to ``Field``.

   .. grid-item-card:: Hydrographic network UML diagrams
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: hydrographic-network-uml-diagrams
      :link-type: doc

      Class diagrams and runtime flows for the hydrographic
      network builders, reference vs generated networks, and
      stream support resolution.

   .. grid-item-card:: Simulated active-network inventory
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: hydrographic-network-simulated-active-inventory
      :link-type: doc

      Inventory of what one persisted run exposes for the
      simulated active network: fields, metrics, figures, and the
      Python access path.

.. toctree::
   :hidden:
   :maxdepth: 1

   support-selection-guide
   spatial-support-uml-diagrams
   hydrographic-network-uml-diagrams
   hydrographic-network-simulated-active-inventory
