ETP
===

``etp`` loads potential evapotranspiration forcing. It feeds the solver's diffuse
evapotranspiration (EVT) process and gives climatic context alongside recharge,
precipitation, and temperature forcing.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - A local potential evapotranspiration file (station chronicles or a gridded
       NetCDF/GeoTIFF) is authoritative.
     - ``custom``
   * - ``sim2``
     - SIM2 gridded potential evapotranspiration should be retrieved over the project period.
     - ``sim2``

Minimal example
---------------

.. code-block:: toml

   [data.etp]
   date_start = "2000-01-01"
   date_end = "2002-12-31"

   [[data.etp.sources]]
   source = "sim2"
   extent = "watershed"

All field definitions, types, and defaults live in the generated reference:
:doc:`/user_guide/config_reference/data`.

Loaded shape
------------

``EtpManager`` (``hydromodpy.data.variables.etp.manager``, in the :mod:`hydromodpy.data`
layer) returns one of two record shapes depending on the source:

- ``custom`` pointed at a directory of station files returns a list of ``PointRecord``: one
  entry per station, each carrying a ``datetime``/``value`` time series, a start and end date,
  and the resolved unit.
- ``custom`` pointed at a single ``.nc`` or ``.tif`` file, and every ``sim2`` source, returns a
  list of ``FieldRecord``: a gridded dataset over a bounding box and CRS, with the source period
  as ``date_start``/``date_end``.

Both shapes are converted to the internal unit ``mm/day`` before reaching downstream code,
whatever unit the source file declares or the SIM2 API returns.

Downstream uses
---------------

- the solver EVT package, built from ``flow.sinks_sources.etp``
  (:doc:`/user_guide/config_reference/flow`); both the MODFLOW 6 and the MODFLOW-NWT
  backends assemble it;
- climatic summaries and reporting alongside :doc:`recharge`, :doc:`precipitation`, and
  :doc:`temperature`;
- water-budget checks once ETP has been activated in the flow configuration.

ETP Source: custom
^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` for local potential evapotranspiration forcing.

.. code-block:: toml

   [[data.etp.sources]]
   source = "custom"
   path = "data/etp/etp_daily.nc"
   source_unit = "mm/day"

The :ref:`path <data-etp-sources-path>` field accepts either a
directory of station location and chronicle files, or a single ``.nc``/``.tif`` file; which one
decides the loaded shape described above.

Operational checks:

- set :ref:`source_unit <data-etp-sources-source-unit>` when file metadata do not carry
  explicit units;
- check period coverage, non-negative values, and stress-period aggregation before ETP reaches
  the EVT package;
- :ref:`mask_path <data-etp-sources-mask-path>` can filter stations or clip a gridded source
  to a project mask;
- :ref:`station_ids <data-etp-sources-station-ids>` restricts loading to an explicit station
  list when the source directory holds more stations than needed.

ETP Source: sim2
^^^^^^^^^^^^^^^^

Use ``source = "sim2"`` to retrieve SIM2 potential evapotranspiration fields.

.. code-block:: toml

   [[data.etp.sources]]
   source = "sim2"
   extent = "watershed"

:ref:`extent <data-etp-sources-extent>` selects the bounding box used for the request: the
delineated watershed, or the broader study area.

Operational checks:

- use the climatic summary for pre-solver checks, then inspect water-budget terms after ETP has
  been activated in the flow configuration;
- set :ref:`force_refresh <data-etp-sources-force-refresh>` to bypass the cache when the SIM2
  payload needs a fresh download.
