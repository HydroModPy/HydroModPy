Humidity
========

``humidity`` loads relative-humidity forcing and climate context. Loaded records
can support atmospheric forcing summaries, evapotranspiration context, and
HELP-style soil-water coupling, alongside other climate variables such as
:doc:`temperature` and :doc:`wind`.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - A local humidity field or station series is authoritative.
     - ``custom``
   * - ``sim2``
     - SIM2 gridded relative humidity should be retrieved over the project
       period.
     - ``sim2``

Minimal example
---------------

.. code-block:: toml

   [[data.humidity.sources]]
   source = "sim2"
   extent = "watershed"

Field defaults, types, and validators for every key shown here are documented
in the generated reference: :doc:`/user_guide/config_reference/data`.

Loaded shape
------------

A ``custom`` source pointed at a directory is read station by station: each
location and its chronicle are combined into point records carrying a
relative-humidity time series. A ``custom`` source pointed at a single ``.nc``
or ``.tif`` file, and every ``sim2`` source, returns a gridded field record
instead; ``sim2`` always covers the full grid for the requested bbox and
period. Both paths normalize values to HydroModPy's internal humidity unit,
percent (``%``). See :ref:`path <data-humidity-sources-path>` for the field
that decides which shape is loaded.

Downstream uses
---------------

- atmospheric forcing summaries alongside :doc:`temperature`, :doc:`wind`, and
  :doc:`radiation`;
- evapotranspiration context;
- HELP-style soil-water balance coupling.

Humidity Source: custom
^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` for local humidity fields or station series.

.. code-block:: toml

   [[data.humidity.sources]]
   source = "custom"
   path = "data/humidity/humidity.nc"
   source_unit = "%"

Check whether values are fractions or percentages before any preprocessing
uses them, and check units, period coverage, and spatial alignment with the
other forcing families. Set :ref:`source_unit <data-humidity-sources-source-unit>`
when the file metadata do not carry explicit units.

Humidity Source: sim2
^^^^^^^^^^^^^^^^^^^^^

Use ``source = "sim2"`` to retrieve SIM2 humidity fields.

.. code-block:: toml

   [[data.humidity.sources]]
   source = "sim2"
   extent = "watershed"

The overview climatic summary panel plots precipitation and ETP only, so
humidity has no dedicated figure. Check the loaded records directly: period
coverage, unit convention, and spatial support.
