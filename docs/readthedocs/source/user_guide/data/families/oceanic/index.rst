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

Gallery status
--------------

The current Nancon reference is inland, so it is not the right practical case
for oceanic data. A future gallery case should use a coastal basin and show the
station or boundary-stage chronicle directly on the oceanic pages.

.. toctree::
   :maxdepth: 1

   custom
   shom
   constant
