Radiation
=========

``radiation`` loads atmospheric and visible radiation components. It supports climatic
forcing summaries, potential evapotranspiration context, and HELP coupling in the
hydrological preprocessing chain.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - A local radiation field or station chronicle is authoritative.
     - ``custom``
   * - ``sim2``
     - SIM2 gridded radiation should be retrieved over the project period.
     - ``sim2``

Field details for both sources, including ``components``, ``path``, and the shared
timeseries selection fields, are defined in the generated reference: see
:doc:`/user_guide/config_reference/data`, section
:ref:`data.radiation <data-radiation>`.

Minimal example
---------------

.. code-block:: toml

   [[data.radiation.sources]]
   source = "sim2"
   components = ["atmospheric", "visible"]
   extent = "watershed"

The :ref:`components <data-radiation-sources-components>` field accepts ``atmospheric``
and ``visible``, either alone or together. Only the ``sim2`` loader acts on it: it issues
one request per selected component. A ``custom`` source is read as the file is written,
so the file itself decides which signal is loaded.

Loaded shape
------------

Every source is normalized to the internal unit ``MJ/m2/j``. A ``sim2`` source returns one
record per requested component, each a full gridded ``FieldRecord`` over the requested
extent: ``atmospheric`` maps to the SIM2 parameter ``DLI_Q`` and ``visible`` maps to
``SSI_Q``. A ``custom`` source accepts a directory of station location and chronicle CSVs,
or a single NetCDF/GeoTIFF file, and returns point or field records depending on that
input shape.

Downstream code expects the unit to already be ``MJ/m2/j`` after loading. Set
:ref:`source_unit <data-radiation-sources-source-unit>` when a custom NetCDF or GeoTIFF
file does not expose units in its own metadata. Confirm units and
period coverage before using radiation in preprocessing.

Radiation Source: custom
^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` for local radiation fields or station series.

.. code-block:: toml

   [[data.radiation.sources]]
   source = "custom"
   path = "data/radiation/radiation.nc"

Check units, date coverage, and spatial support, and check which radiation signal the
file actually holds: the ``custom`` loader does not select it for you.

Radiation Source: sim2
^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "sim2"`` to retrieve SIM2 radiation fields.

.. code-block:: toml

   [[data.radiation.sources]]
   source = "sim2"
   components = ["atmospheric", "visible"]
   extent = "watershed"

The overview climatic summary panel plots precipitation and ETP only, so radiation has
no dedicated figure. Check the returned records directly: one per requested component,
over the requested period and extent.

Downstream uses
---------------

- :doc:`etp` context, when potential evapotranspiration is derived alongside radiation
  forcing.
- HELP coupling in the hydrological preprocessing chain, which expects daily global
  solar radiation in a compatible unit.
- Generic solver-ready forcing assembly, which converts and aggregates radiation the
  same way as any other climatic variable.
