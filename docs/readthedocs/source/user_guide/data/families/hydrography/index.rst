Hydrography
===========

``hydrography`` loads river-network geometries. The network can be used for
overview maps, drainage interpretation, mesh constraints, and comparison with
simulated active networks.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - A local river network is authoritative.
     - :doc:`custom`
   * - ``bdtopage``
     - The French BD Topage reference network is the intended public source.
     - :doc:`bdtopage`
   * - ``osm``
     - OpenStreetMap waterway geometries are sufficient or useful for broader
       screening.
     - :doc:`osm`
   * - ``euhydro``
     - EU-Hydro coverage is the intended continental-scale reference.
     - :doc:`euhydro`

Minimal example
---------------

.. code-block:: toml

   [data]
   types = ["hydrography"]

   [[data.hydrography.sources]]
   source = "bdtopage"

Loaded shape
------------

The loaded payload is a vector river network. Downstream checks usually focus
on spatial alignment, network density, outlet consistency, and whether the
network is suitable as a target for drainage or seepage diagnostics.

Visual check
------------

.. figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_map_hydrography.png
   :alt: Nancon hydrography layer
   :width: 100%

   The first check is visual: rivers should sit inside the expected basin and
   have a plausible density for the data source and model objective.

Provider-specific overlay
-------------------------

.. figure:: /_static/capability_gallery/geographic/geographic_bdtopage_hydrography_overlay.png
   :alt: BD Topage hydrography overlay
   :width: 100%

   A source-specific overlay is useful when the question is about the provider
   itself rather than the complete basin identity card.

Downstream uses
---------------

- hydrography panels in data overviews;
- river constraints for meshes;
- drainage target interpretation;
- active-network comparison after simulation.

.. toctree::
   :maxdepth: 1

   custom
   bdtopage
   osm
   euhydro
