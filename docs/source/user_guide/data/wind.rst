Wind
====

``wind`` loads wind-speed forcing and climate context. It feeds hydrological preprocessing
(PyHELP-style weather input) and gives seasonal context alongside temperature and humidity.
Field definitions, types, and defaults live in the generated reference at
:doc:`/user_guide/config_reference/data`; this page only names them and shows how to use them.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - A local wind raster, NetCDF file, or station chronicle is authoritative.
     - ``custom``
   * - ``sim2``
     - SIM2 ``FF_Q`` wind speed should be retrieved over the project period and extent.
     - ``sim2``

Minimal example
---------------

.. code-block:: toml

   [data.wind]
   date_start = "2000-01-01"
   date_end = "2002-12-31"

   [[data.wind.sources]]
   source = "sim2"
   extent = "watershed"

``date_start`` and ``date_end`` are defined at :ref:`date_start <data-wind-date-start>` and
:ref:`date_end <data-wind-date-end>`. :ref:`source <data-wind-sources-source>` selects the
provider, and :ref:`extent <data-wind-sources-extent>` picks the bounding box.

Loaded shape
------------

``WindManager`` (``hydromodpy.data.variables.wind.manager``, in the :mod:`hydromodpy.data`
layer) normalizes every source to the internal unit ``m/s``. What it returns depends on :ref:`path <data-wind-sources-path>`: a
directory holding a location file plus chronicle CSVs yields one ``PointRecord`` per station,
each carrying a ``datetime``/``value`` time series, a start and end date, and the resolved
unit; a single ``.nc`` or ``.tif`` file, or the ``sim2`` source, yields a ``FieldRecord``: a
gridded dataset over a bounding box and CRS, with the source period as
``date_start``/``date_end``. See ``hydromodpy.data.variables.wind.custom`` for the dispatch
logic.

Downstream uses
---------------

- weather preprocessing for PyHELP-driven hydrology (wind-speed input to evapotranspiration
  estimation), described in :doc:`/theory/hydrology/hydrological-forcing-chain`;
- the shared forcing bridge (``hydromodpy.physics.forcing.forcing_bridge``) used to resolve
  recharge, precipitation, ETP, temperature, and wind sources into homogeneous inputs;
- climatic summaries and reporting alongside :doc:`temperature` and :doc:`humidity`.

Wind Source: custom
^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` for local wind fields or station series. ``path`` can point to a
directory of station files or to a single gridded file, as defined at
:ref:`path <data-wind-sources-path>`.

.. code-block:: toml

   [[data.wind.sources]]
   source = "custom"
   path = "data/wind/wind.nc"
   source_unit = "m/s"

Operational checks:

- set :ref:`source_unit <data-wind-sources-source-unit>` when file metadata are missing or ambiguous;
- check period coverage and spatial support before mixing wind with other climate variables;
- :ref:`mask_path <data-wind-sources-mask-path>` can filter stations or clip a gridded source to a project
  mask;
- :ref:`station_ids <data-wind-sources-station-ids>` restricts loading to an explicit station list when the
  source directory holds more stations than needed.

Wind Source: sim2
^^^^^^^^^^^^^^^^^

Use ``source = "sim2"`` to retrieve SIM2 wind fields.

.. code-block:: toml

   [[data.wind.sources]]
   source = "sim2"
   extent = "watershed"

:ref:`extent <data-wind-sources-extent>` selects the bounding box used for the request: the delineated
watershed, or the broader study area.

Operational checks:

- check unit convention, period coverage, and whether the variable is being used only for
  reporting or for a preprocessing chain;
- set :ref:`force_refresh <data-wind-sources-force-refresh>` to bypass the cache when the SIM2 payload needs a
  fresh download.
