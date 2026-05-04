Geology
========

``geology`` loads geological zones as vector or raster data. HydroModPy can use
those zones as display layers, mesh constraints, field supports, and keys for
hydraulic-property transfer.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - A local geology layer and code field are authoritative.
     - :doc:`custom`
   * - ``brgm_1m``
     - The public 1:1,000,000 BRGM geology layer is the intended regional
       support.
     - :doc:`brgm-1m`
   * - ``brgm_50k``
     - The public 1:50,000 BRGM geology layer is available and the study needs
       finer geological structure.
     - :doc:`brgm-50k`

Minimal example
---------------

.. code-block:: toml

   [data]
   types = ["geology"]

   [[data.geology.sources]]
   source = "brgm_1m"
   extent = "watershed"

Loaded shape
------------

The loaded object should preserve zone geometries and a stable geology code.
When ``values_table_path`` is provided, the code also becomes the join key for
hydraulic-property tables.

Visual check
------------

.. figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_map_geology.png
   :alt: Nancon geology layer with legend
   :width: 100%

   The map is not enough without its legend: the displayed categories must
   remain interpretable after clipping, reprojection, and optional property
   joins.

Property transfer check
-----------------------

.. figure:: /_static/user_guide/data/geology_property_brittany_local.png
   :alt: Local geology-to-hydraulic-conductivity transfer case
   :width: 100%

   This generated data-doc case starts from a versioned BRGM-style geology
   vector, joins a local property table, rasterizes the geology support on a
   mesh, and displays the resulting ``K`` field. It is the most direct
   documentation proof that geology can become a solver-facing parameter
   support instead of remaining a background map.

.. figure:: /_static/capability_gallery/hydraulic_properties/hydraulic_conductivity_geology_transfer_brittany.png
   :alt: Geology-driven hydraulic conductivity transfer
   :width: 100%

   Geology becomes solver-relevant when zones are transferred to hydraulic
   properties or model supports. Use this kind of figure to verify that the
   geology code has not collapsed into a single default category.

Downstream uses
---------------

- geology maps in data overviews;
- mesh constraints and interfaces;
- support selection for fields;
- hydraulic conductivity, storage, or zone-based parameterization.

.. toctree::
   :maxdepth: 1

   custom
   brgm-1m
   brgm-50k
