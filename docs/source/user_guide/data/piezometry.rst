Piezometry
==========

``piezometry`` loads groundwater-level observation wells and chronicles. It is
used to inspect aquifer state information, calibrate heads or depths, and
compare simulated groundwater levels against observed records.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - Local piezometer records are authoritative.
     - ``custom``
   * - ``hubeau``
     - Hub'Eau piezometry should discover or download public observations.
     - ``hubeau``

Minimal example
---------------

.. code-block:: toml

   [data.piezometry]
   date_start = "2000-01-01"
   date_end = "2020-12-31"

   [[data.piezometry.sources]]
   source = "hubeau"
   product = "level"
   extent = "watershed"

Visual check
------------

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_nancon_timeseries_piezometry.png
   :alt: Nancon piezometry time series
   :width: 100%

   Piezometry records should be checked for product meaning, date coverage,
   gaps, and vertical reference before they are compared to simulated heads.

.. figure:: /_static/user_guide/data/observations_local_timeseries_examples.png
   :alt: Local piezometry chronicle alongside other observation families
   :width: 100%

   The middle panel is a local piezometry chronicle. It keeps the groundwater
   level semantics separate from discharge and chemistry even though the file
   convention is similar.

Downstream uses
---------------

- head or depth calibration targets;
- groundwater-state validation;
- basin screening before solver setup;
- comparison reports.

Piezometry Source: custom
^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` when local piezometer files should be trusted over
public discovery.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.piezometry.sources]]
   source = "custom"
   path = "data/piezometry"
   col_id = "station"
   col_x = "x"
   col_y = "y"
   default_crs = "EPSG:2154"
   col_datetime = "date"
   col_value = "level"

Operational checks
""""""""""""""""""

- State whether the value is a level or a depth before using it as a head
  target.
- Keep station CRS and vertical datum assumptions explicit.
- Inspect the rendered chronicle for gaps and physically impossible jumps.


Piezometry Source: hubeau
^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "hubeau"`` to retrieve public French groundwater-level
observations.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.piezometry.sources]]
   source = "hubeau"
   product = "level"
   extent = "watershed"
   nearest = true

Operational checks
""""""""""""""""""

- ``product`` accepts ``level`` or ``depth``; choose the product that matches
  the later comparison.
- ``nearest`` can select nearby usable stations when exact support filtering is
  too strict.
- Verify date coverage and station placement before using the data in
  calibration.

Provider replay
"""""""""""""""

.. figure:: /_static/user_guide/data/hubeau_provider_replay_examples.png
   :alt: Hub'Eau piezometry replay with station inventory and chronicle coverage
   :width: 100%

   The piezometry part of the Hub'Eau replay keeps groundwater-level semantics
   separate from discharge and chemistry. This matters before comparing
   observations to simulated heads.
