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
     - ``custom``
   * - ``bdtopage``
     - The French BD Topage reference network is the intended public source.
     - ``bdtopage``
   * - ``osm``
     - OpenStreetMap waterway geometries are sufficient or useful for broader
       screening.
     - ``osm``
   * - ``euhydro``
     - EU-Hydro coverage is the intended continental-scale reference.
     - ``euhydro``

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

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_map_hydrography.png
   :alt: Nancon hydrography layer
   :width: 100%

   The first check is visual: rivers should sit inside the expected basin and
   have a plausible density for the data source and model objective.

Provider-specific overlay
-------------------------

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_bdtopage_hydrography_overlay.png
   :alt: BD Topage hydrography overlay
   :width: 100%

   A source-specific overlay is useful when the question is about the provider
   itself rather than the complete basin identity card.

Provider comparison
-------------------

.. figure:: /_static/user_guide/data/hydrography_provider_couesnon_comparison.png
   :alt: BD Topage, OSM, and EU-Hydro comparison on the same bbox
   :width: 100%

   When several public providers can load the same family, compare them before
   choosing one. The Couesnon replay makes the density and continuity
   differences visible without running a solver.

Local spatial smoke test
------------------------

.. figure:: /_static/user_guide/data/spatial_local_dem_hydrography_example.png
   :alt: Local DEM and hydrography stack
   :width: 100%

   The local data-doc run reads a versioned DEM and a versioned river-network
   vector. It is a compact check for CRS agreement, network density, and
   whether a custom hydrography file is spatially plausible before it is used
   for mesh constraints or active-network interpretation.

Downstream uses
---------------

- hydrography panels in data overviews;
- river constraints for meshes;
- drainage target interpretation;
- active-network comparison after simulation.

Hydrography Source: bdtopage
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "bdtopage"`` when the French BD Topage hydrographic network is
the expected reference.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.hydrography.sources]]
   source = "bdtopage"

Operational checks
""""""""""""""""""

- Check network density against the intended drainage interpretation.
- Check outlet alignment before comparing observed and simulated active
  networks.
- Use a source-specific overlay when documenting that BD Topage itself is the
  provider under test.

Visual reference
""""""""""""""""

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_bdtopage_hydrography_overlay.png
   :alt: BD Topage hydrography overlay
   :width: 100%

   This figure isolates the BD Topage layer so the provider result can be read
   independently from geology or station panels.

Provider replay
"""""""""""""""

.. figure:: /_static/user_guide/data/hydrography_provider_replay_examples.png
   :alt: Hydrography provider replay including BD Topage samples
   :width: 100%

   The provider replay shows committed BD Topage samples separately from the
   broader local river network. This keeps the source under test readable
   before it is clipped, rasterized, or compared with simulated active
   networks.

Provider comparison
"""""""""""""""""""

.. figure:: /_static/user_guide/data/hydrography_provider_couesnon_comparison.png
   :alt: Couesnon hydrography comparison including BD Topage
   :width: 100%

   In the Couesnon replay bbox, BD Topage provides an intermediate network
   density between OSM and EU-Hydro. This is the kind of first-order provider
   effect that should be visible before a network is used as a meshing or
   drainage reference.


Hydrography Source: custom
^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` when a local river-network layer should be trusted
over public providers.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.hydrography.sources]]
   source = "custom"
   path = "data/hydrography/rivers.gpkg"
   rasterize_field = "FID"

Operational checks
""""""""""""""""""

- The network CRS must match or be safely reprojectable to the project CRS.
- The layer should cover the modeled basin and its outlet neighborhood.
- ``rasterize_field`` should identify stable features when raster products are
  generated.
- A correct file path is not enough; inspect the map overlay.


Hydrography Source: euhydro
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "euhydro"`` when EU-Hydro coverage is the intended
continental-scale river-network reference.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.hydrography.sources]]
   source = "euhydro"

Operational checks
""""""""""""""""""

- Check that the selected extent is large enough to retrieve the expected
  network around the basin.
- Compare network density with the modeling scale; continental products may be
  too coarse for small headwater studies.
- Inspect the river overlay before using the network as a mesh or drainage
  target.

Provider replay
"""""""""""""""

.. figure:: /_static/user_guide/data/hydrography_provider_replay_examples.png
   :alt: Hydrography provider replay including EU-Hydro
   :width: 100%

   The replay figure includes a committed EU-Hydro GPKG on the Couesnon bbox.
   This keeps the provider visible in the documentation while making clear that
   it is coarser than local or national hydrography on small headwater windows.

Provider comparison
"""""""""""""""""""

.. figure:: /_static/user_guide/data/hydrography_provider_couesnon_comparison.png
   :alt: Couesnon hydrography comparison including EU-Hydro
   :width: 100%

   EU-Hydro retrieves fewer line features on this bbox. That is useful
   evidence: continental coverage is not automatically the right support for a
   small basin, and the comparison should be inspected before selecting it as a
   network reference.


Hydrography Source: osm
^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "osm"`` when OpenStreetMap waterway geometries are acceptable
for screening, teaching, or projects where a public local reference is not
available.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.hydrography.sources]]
   source = "osm"
   waterway_types = ["river", "stream"]

Operational checks
""""""""""""""""""

- ``waterway_types`` controls which OSM waterway classes are retained.
- OSM completeness can vary by region, so visual inspection is mandatory.
- Avoid treating OSM density as a hydrological truth without local validation.

Provider replay
"""""""""""""""

.. figure:: /_static/user_guide/data/hydrography_provider_replay_examples.png
   :alt: Hydrography provider replay including OSM
   :width: 100%

   The replay figure includes a committed OSM GPKG on the Couesnon bbox. It
   should be read as a provider payload check, not as proof that OSM is always
   complete enough for modeling.

Provider comparison
"""""""""""""""""""

.. figure:: /_static/user_guide/data/hydrography_provider_couesnon_comparison.png
   :alt: Couesnon hydrography comparison including OSM
   :width: 100%

   On this bbox, OSM contributes the densest small-stream network. That can be
   valuable for screening, but it also reinforces why OSM needs visual
   validation against local knowledge or an institutional reference before it
   becomes a modeling constraint.
