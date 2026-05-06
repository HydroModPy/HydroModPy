Hydrometry
==========

``hydrometry`` loads discharge stations and streamflow chronicles. The family
is used for basin screening, outlet-response checks, calibration objectives,
and post-simulation hydrograph comparison.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - Local station and discharge files are authoritative.
     - ``custom``
   * - ``hubeau``
     - Hub'Eau hydrometry should discover or download public discharge data.
     - ``hubeau``

Minimal example
---------------

.. code-block:: toml

   [data.hydrometry]
   date_start = "2000-01-01"
   date_end = "2020-12-31"

   [[data.hydrometry.sources]]
   source = "hubeau"
   product = "QmnJ"
   extent = "watershed"

Visual check
------------

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_nancon_timeseries_discharge.png
   :alt: Nancon discharge time series
   :width: 100%

   The discharge chronicle should show station identity, date coverage, gaps,
   and magnitude before it is used for calibration or comparison.

.. figure:: /_static/user_guide/data/observations_local_timeseries_examples.png
   :alt: Local hydrometry chronicle alongside other observation families
   :width: 100%

   The first panel is a local hydrometry chronicle. It illustrates the
   minimum custom-source check: the station has a readable period, magnitude,
   and event structure before it becomes a calibration or comparison target.

Downstream uses
---------------

- observed hydrographs;
- calibration objectives;
- discharge comparison metrics;
- active-network interpretation when combined with hydrography.

Hydrometry Source: custom
^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` when project-owned discharge station and chronicle
files should be authoritative.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.hydrometry.sources]]
   source = "custom"
   path = "data/hydrometry"
   col_id = "station"
   col_x = "lon"
   col_y = "lat"
   default_crs = "EPSG:4326"
   col_datetime = "date"
   col_value = "Q"
   station_ids = ["J1234010"]

Operational checks
""""""""""""""""""

- the location file must identify stations and coordinates;
- chronicle files must expose datetime and value columns;
- ``source_unit`` should be set when units are not self-evident;
- rendered hydrographs should be inspected before the data are used in a
  calibration objective.


Hydrometry Source: hubeau
^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "hubeau"`` when public French discharge observations should be
discovered and downloaded through Hub'Eau.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.hydrometry.sources]]
   source = "hubeau"
   product = "QmnJ"
   extent = "watershed"
   require_observations = true

Operational checks
""""""""""""""""""

- ``product`` selects the discharge product; daily discharge commonly uses
  ``QmnJ``.
- ``require_observations`` filters out stations without usable records over
  the requested period.
- ``fallback_search_radius_km`` can be useful when the watershed has no station
  inside its exact support.
- Cache and lockfile metadata should be preserved for reproducible studies.

Provider replay
"""""""""""""""

.. figure:: /_static/user_guide/data/hubeau_provider_replay_examples.png
   :alt: Hub'Eau hydrometry replay with station inventory and chronicle coverage
   :width: 100%

   The hydrometry part of the Hub'Eau replay shows why station metadata and
   chronicle coverage must be checked together. The discharge product should be
   readable before it becomes an objective or comparison target.
