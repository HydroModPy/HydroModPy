Recharge
========

``recharge`` loads or generates diffuse recharge forcing. It can be consumed
directly by MODFLOW-style flow processes, inspected in hydrological summaries,
or used in controlled analytical and synthetic cases.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - Local recharge files are authoritative.
     - ``custom``
   * - ``sim2``
     - SIM2 gridded recharge should be retrieved over the project period.
     - ``sim2``
   * - ``synthetic``
     - A deterministic recharge sequence is needed for tests or examples.
     - ``synthetic``

Minimal example
---------------

.. code-block:: toml

   [data.recharge]
   date_start = "2000-01-01"
   date_end = "2002-12-31"

   [[data.recharge.sources]]
   source = "sim2"
   extent = "watershed"

Visual check
------------

Use the climatic summary for source-period checks and the water budget for
post-solver confirmation that recharge was consumed as intended.

.. figure:: /_static/user_guide/data/forcing_local_recharge_runoff_example.png
   :alt: Local custom recharge source series
   :width: 100%

   For ``custom`` recharge, this is the first useful figure: the chronicle
   shows coverage and aggregate input before stress-period aggregation.

.. figure:: /_static/user_guide/data/sim2_grid_forcing_example.png
   :alt: SIM2 recharge grid and climate cycle
   :width: 100%

   For ``sim2`` recharge, inspect the grid support as well as the temporal
   forcing context. A valid file path is not enough if the spatial support or
   selected period is wrong.

Recharge Source: custom
^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` when a local recharge raster, NetCDF file, or time
series is the reference input.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.recharge.sources]]
   source = "custom"
   path = "data/recharge/recharge_daily.nc"
   source_unit = "mm/day"
   extent = "watershed"

Operational checks
""""""""""""""""""

- Set ``source_unit`` when file metadata are missing or ambiguous.
- Check the date dimension against ``date_start`` and ``date_end``.
- Confirm whether the values represent recharge only or already include runoff
  partitioning.
- Inspect solver aggregation when the recharge is used in a transient model.


Recharge Source: sim2
^^^^^^^^^^^^^^^^^^^^^

Use ``source = "sim2"`` when SIM2 recharge should be retrieved for the project
support and period.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.recharge.sources]]
   source = "sim2"
   extent = "watershed"

Operational checks
""""""""""""""""""

- The configured period should match the intended hydrological or simulation
  window.
- Cache metadata should be preserved when runs must be reproducible.
- Inspect forcing summaries before looking at model response.

Provider replay
"""""""""""""""

.. figure:: /_static/user_guide/data/sim2_grid_forcing_example.png
   :alt: SIM2 replay with recharge grid and climate cycle
   :width: 100%

   The recharge replay shows both the gridded support and the selected period.
   This is the provider-level check to perform before values are aggregated
   into solver stress periods.


Recharge Source: synthetic
^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "synthetic"`` for deterministic recharge series in tests,
tutorials, and analytical comparisons.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.recharge.sources]]
   source = "synthetic"
   values = [0.0, 2.0, 5.0, 2.0]
   start_date = "2000-01-01"
   freq = "D"
   source_unit = "mm/day"
   runoff_ratio = 0.0

Operational checks
""""""""""""""""""

- State whether ``values`` are absolute values or part of a waveform setup.
- Keep ``runoff_ratio`` explicit.
- Synthetic recharge is ideal for verifying solver assembly because the input
  chronology is known exactly.
