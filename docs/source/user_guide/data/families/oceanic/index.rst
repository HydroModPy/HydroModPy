Oceanic
========

``oceanic`` loads or declares sea-level information for coastal boundary
conditions and coastal project context. It is separate from meteorological
forcing because its downstream role is usually a boundary stage or a controlled
coastal reference level.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - Local sea-level files are authoritative.
     - :doc:`custom`
   * - ``shom``
     - SHOM observations should be discovered or retrieved.
     - :doc:`shom`
   * - ``constant``
     - A controlled fixed sea level is enough for the case.
     - :doc:`constant`

Minimal example
---------------

.. code-block:: toml

   [data.oceanic]
   date_start = "2020-01-01"
   date_end = "2020-12-31"

   [[data.oceanic.sources]]
   source = "constant"
   value = 0.0

Checks
------

- Confirm whether values represent absolute sea level, anomaly, or model-stage
  convention.
- Keep vertical datum assumptions explicit.
- For SHOM or custom time series, check station location, date coverage, and
  units before the data are mapped to a boundary condition.

Local deterministic run
-----------------------

The repository includes a small local ``oceanic`` case under
``hydromodpy/data/variables/oceanic/cases``. It is not a coastal basin study;
it is a communication and regression asset that proves the custom source can be
loaded, summarized, and plotted without requiring network access.

.. figure:: /_static/user_guide/data/oceanic_local_stage_example.png
   :alt: Local custom oceanic sea-level chronicle
   :width: 100%

   The figure shows the loaded stage values and the returned mean sea level
   used by the data-only case. This is the minimum useful visual contract for
   ``custom`` oceanic data: timestamps, values, units, and summary level are
   visible.

Remaining gallery gap
---------------------

The current Nancon reference is inland, so it is not the right practical case
for oceanic data. A future gallery case should use a coastal basin and show the
station or boundary-stage chronicle directly on the oceanic pages.

.. toctree::
   :maxdepth: 1

   custom
   shom
   constant
