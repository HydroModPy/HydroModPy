Precipitation
=============

``precipitation`` loads liquid, solid, or total precipitation forcing. It is a
meteorological input for hydrological preprocessing and a diagnostic context
for recharge and runoff interpretation.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - A local precipitation raster, NetCDF file, or station-derived series is authoritative.
     - :doc:`custom-data`
   * - ``sim2``
     - SIM2 gridded precipitation should be retrieved over the project period.
     - :doc:`provider-replay-cases`

Minimal example
---------------

.. code-block:: toml

   [data.precipitation]
   date_start = "2000-01-01"
   date_end = "2002-12-31"

   [[data.precipitation.sources]]
   source = "sim2"
   components = ["total"]
   extent = "watershed"

All field definitions, types, and defaults live in the generated reference:
:doc:`/user_guide/config_reference/data`.

Loaded shape
------------

``PrecipitationManager`` (``hydromodpy.data.variables.precipitation.manager``, in the
:mod:`hydromodpy.data` layer) returns one of two record shapes depending on the source:

- ``custom`` pointed at a directory of station files returns a list of ``PointRecord``: one
  entry per station, each carrying a ``datetime``/``value`` time series, a start and end date,
  and the resolved unit.
- ``custom`` pointed at a single ``.nc`` or ``.tif`` file, and every ``sim2`` source, returns a
  list of ``FieldRecord``: a gridded dataset over a bounding box and CRS, with the source period
  as ``date_start``/``date_end``. SIM2 returns one ``FieldRecord`` per requested component.

Both shapes are converted to the internal unit ``mm/day`` before reaching downstream code,
whatever unit the source file declares or the SIM2 API returns.

Visual check
------------

.. figure:: /_static/user_guide/data/sim2_grid_forcing_example.png
   :alt: SIM2 precipitation and temperature monthly summary
   :width: 100%

   The right panel shows the kind of monthly total that should be inspected for
   SIM2 precipitation before it is compared with recharge, runoff, or solver
   budget terms. See :doc:`runs-and-figures` for how this figure is regenerated.

Downstream uses
---------------

- hydrological preprocessing for PyHELP-driven recharge (daily total precipitation, one of
  the D4 weather inputs);
- the shared forcing bridge used to combine recharge, precipitation, ETP, and temperature
  sources into homogeneous inputs;
- open-water rainfall applied directly to lake surfaces alongside ETP-derived evaporation,
  in the lake meteorological forcing step;
- climatic summaries and reporting alongside :doc:`recharge`, :doc:`etp`, and :doc:`temperature`.

Precipitation Source: custom
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` for local precipitation rasters, NetCDF files, or
station-derived series.

.. code-block:: toml

   [[data.precipitation.sources]]
   source = "custom"
   path = "data/precipitation/precipitation.nc"
   source_unit = "mm/day"

The :ref:`path <data-precipitation-sources-path>` field accepts either a directory of station
location and chronicle files, or a single ``.nc``/``.tif`` file; which one decides the loaded
shape described above.

Operational checks:

- set :ref:`source_unit <data-precipitation-sources-source-unit>` when file metadata do not
  carry explicit units;
- check period coverage, units, and spatial support before the data are used in hydrological
  preprocessing, and check which signal the file holds: ``components`` is read by the ``sim2``
  loader only, so a ``custom`` file is taken as written;
- :ref:`mask_path <data-precipitation-sources-mask-path>` can filter stations or clip a gridded
  source to a project mask;
- :ref:`station_ids <data-precipitation-sources-station-ids>` restricts loading to an explicit
  station list when the source directory holds more stations than needed.


Precipitation Source: sim2
^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "sim2"`` to retrieve SIM2 precipitation fields.

.. code-block:: toml

   [[data.precipitation.sources]]
   source = "sim2"
   components = ["liquid", "solid", "total"]
   extent = "watershed"

:ref:`components <data-precipitation-sources-components>` selects which precipitation signal
is loaded from the provider: liquid rain, solid snow, or their sum. One record is returned per
selected component. :ref:`extent <data-precipitation-sources-extent>` selects the bounding box
used for the request: the delineated watershed, or the broader study area.

Operational checks:

- inspect the climatic summary to verify that the requested period and selected components
  are available;
- set :ref:`force_refresh <data-precipitation-sources-force-refresh>` to bypass the cache when
  the SIM2 payload needs a fresh download.

Provider replay
"""""""""""""""

.. figure:: /_static/user_guide/data/sim2_grid_forcing_example.png
   :alt: SIM2 replay with monthly precipitation summary
   :width: 100%

   The monthly precipitation panel is the first provider replay to inspect
   before comparing precipitation with recharge, runoff, or solver budgets.
   The full replay case is described in :doc:`provider-replay-cases`.
