Soil Moisture
=============

``soil_moisture`` loads soil-moisture fields or time series. It is used as land-surface
forcing context and as a hydrological diagnostic, read alongside recharge and the other
climatic forcings rather than on its own.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - A local soil-moisture file or station series is authoritative.
     - ``custom``
   * - ``sim2``
     - SIM2 soil-moisture (soil wetness index) should be retrieved over the project
       period.
     - ``sim2``

Minimal example
---------------

.. code-block:: toml

   [data]
   types = ["soil_moisture"]

   [[data.soil_moisture.sources]]
   source = "sim2"
   extent = "watershed"

See :doc:`/user_guide/config_reference/data` for every field of
:ref:`data.soil_moisture <data-soil-moisture>` and
:ref:`data.soil_moisture.sources <data-soil-moisture-sources>`, including types and
defaults.

Loaded shape
------------

For ``source = "custom"``, :ref:`path <data-soil-moisture-sources-path>` decides the shape: a directory of station files
loads a list of point time series, one per station, while a single ``.nc`` or ``.tif``
file loads a spatial field instead. For ``source = "sim2"``, the loader always returns
the full spatial grid as a field, fetching the SIM2 soil wetness index parameter.

Either way, values are normalized to the internal unit ``%``. Downstream code treats
``soil_moisture`` like any other climatic variable: a homogeneous series is extracted
(station average, or spatial mean of a field), converted to solver units, and aligned
to the simulation stress periods before use, as described in
:doc:`/theory/hydrology/hydrological-forcing-chain`.

Soil Moisture Source: custom
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` for local soil-moisture fields or station series.

.. code-block:: toml

   [[data.soil_moisture.sources]]
   source = "custom"
   path = "data/soil_moisture/soil_moisture.nc"

Check whether values are fractions, percentages, or volumetric water content before
using them. Set :ref:`source_unit <data-soil-moisture-sources-source-unit>` when the
file metadata do not make the convention explicit.

Soil Moisture Source: sim2
^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "sim2"`` to retrieve SIM2 soil-moisture fields.

.. code-block:: toml

   [[data.soil_moisture.sources]]
   source = "sim2"
   extent = "watershed"

The overview climatic summary panel plots precipitation and ETP only, so soil
moisture has no dedicated figure. Check period coverage, the unit convention, and
whether the data are used as a diagnostic or as a preprocessing input. The configured
project period should match the intended hydrological or simulation window; see
:ref:`date_start <data-soil-moisture-date-start>` and
:ref:`date_end <data-soil-moisture-date-end>`.

Downstream uses
---------------

- hydrological diagnostics, read alongside recharge and other climatic forcing;
- land-surface forcing context handled by the generic forcing bridge, see
  :doc:`/theory/hydrology/hydrological-forcing-chain`;
- climatic summaries produced by the data-retrieval workflow, see
  :doc:`retrieval-workflow`.
