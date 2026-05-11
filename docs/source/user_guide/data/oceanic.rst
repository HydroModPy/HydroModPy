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
     - ``custom``
   * - ``shom``
     - SHOM observations should be discovered or retrieved.
     - ``shom``
   * - ``constant``
     - A controlled fixed sea level is enough for the case.
     - ``constant``

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

Oceanic Source: constant
^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "constant"`` for controlled examples, inland tests that need a
neutral oceanic placeholder, or coastal sensitivity studies with a fixed stage.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.oceanic.sources]]
   source = "constant"
   value = 0.0

Operational checks
""""""""""""""""""

- State the vertical datum represented by ``value``.
- Keep the value in the same conceptual convention as the boundary condition
  that will consume it.
- Do not treat a constant source as an observation; it is a controlled input.


Oceanic Source: custom
^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` when project-owned sea-level or coastal-stage files
should be authoritative.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.oceanic.sources]]
   source = "custom"
   path = "data/oceanic/sea_level.csv"
   col_datetime = "date"
   col_value = "stage"
   source_unit = "m"

Operational checks
""""""""""""""""""

- Document vertical datum and sign convention.
- Check station or boundary location.
- Confirm date coverage before a transient coastal boundary consumes the data.


Oceanic Source: shom
^^^^^^^^^^^^^^^^^^^^

Use ``source = "shom"`` when SHOM sea-level observations should be discovered
or downloaded for a coastal project.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.oceanic.sources]]
   source = "shom"
   extent = "study_area"
   nearest = true

Operational checks
""""""""""""""""""

- ``nearest`` can help select a usable tide-gauge station near the study area.
- ``fallback_search_radius_km`` should be documented when it changes station
  selection.
- Preserve cache and lockfile metadata for reproducibility.
- Always record the vertical datum assumption before mapping values to a
  boundary stage.

Provider replay
"""""""""""""""

.. figure:: /_static/user_guide/data/shom_provider_replay_example.png
   :alt: SHOM provider replay for one coastal sea-level station
   :width: 100%

   This replay uses committed sample artifacts rather than a live SHOM request.
   It shows the two checks that a future coastal gallery case should keep on
   the same page: station selection and boundary-stage chronicle.
