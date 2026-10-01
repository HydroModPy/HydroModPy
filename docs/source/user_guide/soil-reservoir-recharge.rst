Recharge from a soil reservoir
==============================

.. note::

   Use this page when the question is: "can the recharge come from the rain
   and the ETP rather than from the SIM2 drainage, and how do I check it
   before I run MODFLOW?"

The SIM2 drainage (``DRAINC``) that ``[data.recharge] source = "sim2"`` loads
is the water leaving the bottom of the ISBA soil column. Since 2016 it keeps
about 0.3 mm/day all summer on the Nancon, a slow release that belongs to a
groundwater store. Fed to MODFLOW, that memory is counted twice, and a
calibration compensates with an aquifer that stores too little.

The soil reservoir computes a recharge that carries no such memory. Each day
it fills a soil store with the rain, empties it by evapotranspiration, and
sends what overflows to the water table. MODFLOW then builds the slow response
itself, and the drains at the ground surface return the water of saturated
ground to the streams. MODFLOW 6 only.

What it computes
----------------

Each SAFRAN cell of the forcing grid is one soil column, or several with a
soil capacity map (below). Every day, in this order:

1. the rain reaches the soil: ``W = S + P``;
2. the soil evaporates ``ETR = min(W, kc x ETP x min(1, W / (alpha x ru)))``,
   the full rate while the store holds more than ``alpha x ru``, less below;
3. what exceeds ``ru`` leaves the soil: ``Pe = max(0, W - ETR - ru)``, and
   ``S`` keeps the rest;
4. ``Pe`` crosses the unsaturated zone, delayed by ``transit_time`` when it is
   not zero, and reaches the water table as recharge;
5. the ETP the soil left unmet, ``kc x ETP - ETR``, is drawn from the water
   table where it is shallow, when ``flow.active_sinks_sources`` lists
   ``"etp"``.

``alpha`` is ``1 - p`` of FAO-56 (Allen et al. 1998) and the ``LP`` of HBV
(Seibert and Vis 2012). A sealed share of the area (``impervious_fraction``)
runs off at once; a ``bypass_fraction`` of the rain skips the soil. Both are
zero by default. The balance ``P = ETR + recharge + runoff + change of the
stores`` closes to machine precision on every column and every day.

The recharge reaches MODFLOW as a daily grid on the SAFRAN cells, averaged
over each stress period like any gridded recharge. A daily recharge is zero
on most summer days: this is the point.

Declaring it
------------

.. code-block:: toml

   [data]
   types = ["dem", "hydrography", "hydrometry", "precipitation", "etp"]

   [[data.precipitation.sources]]
   source = "sim2"
   extent = "watershed"

   [[data.etp.sources]]
   source = "sim2"
   extent = "watershed"

   [flow]
   active_sinks_sources = ["recharge", "etp"]
   active_bc = ["drainage"]
   first_period_steady = false

   [flow.ic]
   type = "steady_state"

   [flow.sinks_sources.recharge.soil]
   ru = "150 mm"

The dates of the rain and of the ETP are those of ``[simulation.time]``. The
section replaces ``[data.recharge]`` and ``[data.runoff]``: a file that keeps
either is refused, since ISBA took its drainage and its runoff from the same
rain. The water of saturated ground reaches the streams through the drains
(``active_bc = ["drainage"]``), so a lake needs a stream network (``"sfr"``)
to receive it.

The soil section loads ``[data.precipitation]`` and ``[data.etp]`` even when
``data.types`` omits them: the planner infers both straight from
``[flow.sinks_sources.recharge.soil]``. Removing ``"precipitation"`` or
``"etp"`` from ``data.types`` does not switch them off; remove the
``[[data.precipitation.sources]]`` or ``[[data.etp.sources]]`` block instead.

Only ``ru`` is required. The other keys (``alpha``, ``kc``,
``impervious_fraction``, ``bypass_fraction``, ``transit_time``, ``spinup``),
their defaults and their ranges are listed with the ``[flow]`` section of the
configuration reference (:doc:`config_reference/flow`). ``alpha`` is
tabulated only for crops (FAO-56 gives ``p`` per crop, and ``alpha = 1 - p``)
or calibrated (the ``LP`` of HBV); no value is published for a mixed land
cover, so keep it between 0.5 and 0.7. ``kc = 1`` treats the cover as the
reference grass of FAO-56, which tabulates ``kc`` for crops only.

The ETP the soil leaves unmet is drawn from the water table at the full rate
when the head stands at the drain elevation of the cell, and linearly less
down to ``extinction_depth`` below it, 1 m by default:

.. code-block:: toml

   [flow.sinks_sources.etp]
   extinction_depth = "2 m"    # deeper roots draw from a deeper water table

The first stress period must not be steady: a steady first day would hold the
recharge of that day alone, zero after a dry day, and the run would start from
a drained aquifer. Write ``first_period_steady = false`` and
``[flow.ic] type = "steady_state"``: the run then starts from the steady state
under the mean recharge of the whole run (see :doc:`initialization`).

Checking the soil alone
-----------------------

.. code-block:: bash

   hmp run step6_soil_reservoir.toml --until load_data

The run stops after loading the data. It delineates the catchment, loads the
rain and the ETP, computes the soil, prints its budget and writes no run: no
``runs/<name>/`` folder, no catalog row, only the logs under ``.hmp/`` and the
input lock. On the Nancon, 2015 to 2020:

.. code-block:: text

   Soil reservoir, 2015-01-01 to 2020-12-31 (2192 days), 9 SAFRAN cells, 1 capacity class each
   ru 150 mm, alpha 0.6, kc 1.0, impervious 0 %, bypass 0 %, transit time 0 days
   starting soil: 2015 repeated 2 times, settled within 0.1 mm
   mm/year                   mean   2016 least rain   2019 most rain
   precipitation            903.9             790.4           1024.8
   ETP                      698.3             640.7            729.8
   ETR                      547.4             512.0            526.0
   recharge to MODFLOW      356.4             291.1            497.8
   impervious runoff          0.0               0.0              0.0
   storage change            +0.0             -12.6             +1.0
   closure                    0.0               0.0              0.0
   unmet ETP 150.8 mm/year, offered to EVT: the water table gives it only where it is shallow
   recharge July-September: 0.004 mm/day
   recharge for other ru, mm/year: 50 mm 442.8 | 100 mm 392.4 | 150 mm 356.4 | 200 mm 324.8 | 250 mm 295.2
   gauged discharge NANCON: 326.5 mm/year on 2192 of 2192 days, catchment 64.62 km2

Read it in this order. The closure is zero, or the soil is broken. The summer
recharge is near zero for a capacity above 100 mm. The recharge of the other
capacities, beside the gauged discharge, brackets ``ru`` for the calibration:
over several years the recharge plus the sealed runoff should sit slightly
above the gauged discharge, the difference being what the water table
evaporates and what leaves the catchment underground. The unmet ETP line is a
ceiling on that evaporation, not what MODFLOW actually draws: on the full
Nancon run only 6.4 mm/year of the 150.8 mm/year announced here reached the
water table as real evapotranspiration, the rest finding no water table
within ``extinction_depth`` (1 m by default) of the drain elevation. The
discharge line gives a value when one station is loaded, which it takes for
the gauge at the outlet; otherwise it says why it shows none.
``extinction_depth`` is itself calibratable, with
``[calibration.parameters.extinction_depth]``: a deep value lets MODFLOW 6
draw on water further from the drain before the soil budget above reflects it.
``impervious_fraction`` is calibratable too, with
``[calibration.parameters.impervious_fraction]``: each trial recomputes the
sealed runoff and adds it to the discharge the trial is scored against.

To try another capacity: ``--set flow.sinks_sources.recharge.soil.ru=100``.
Each call delineates the catchment again, a few seconds.

A calibration file refuses ``--until``. Run its first steps as a simulation:

.. code-block:: bash

   hmp run run_calibration_soil.toml --until load_data --set workflow.mode=simulation

Calibrating the capacity
------------------------

.. code-block:: toml

   [calibration.parameters.ru]
   bounds = [80.0, 250.0]    # mm

``ru`` is found by name (``hmp config targets <file>`` lists ``soil.ru``). Each
trial computes its own soil. Keep ``alpha``, ``kc``, ``bypass_fraction`` and
``transit_time`` fixed while K and Sy are calibrated: ``kc`` and ``ru`` move the
same annual volume, and a bypass or a long transit time rebuilds the summer
recharge the soil removes. The discharge alone separates ``ru`` from Sy poorly:
both shift the autumn rise. Calibrate in transient phases; a steady phase
cannot run with ``[flow.ic] type = "steady_state"``.

A phase that calibrates ``ru`` writes the recharge of each trial in the
trial's own folder, deleted with the trial. A phase that calibrates K alone,
with ``ru`` frozen, shares one recharge between its trials.

What a run keeps
----------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Path in ``runs/<name>/``
     - Content
   * - ``fields.zarr/forcing/recharge_recharge``
     - The recharge grid MODFLOW received, mm/day, where a SIM2 recharge
       would be.
   * - ``fields.zarr/forcing/soil/``
     - Day by day and per column: ``etr``, ``residual_etp``, ``recharge``,
       ``runoff`` (mm/day), ``soil_storage``, ``transit_storage`` (mm, end of
       day), with the position and capacity of each column.
   * - ``fields.zarr/forcing/runoff/_watershed``
     - The runoff of the sealed share, basin mean, zero without sealed area.
   * - ``tables.parquet/soil_budget.parquet``
     - One row per column and calendar year, and a ``_watershed`` row: the
       budget in mm, with a ``days`` column for a partial year.

A soil capacity map
-------------------

.. code-block:: toml

   [data]
   types = ["dem", "hydrography", "hydrometry", "precipitation", "etp", "soil_capacity"]

   [[data.soil_capacity.sources]]
   source = "custom"
   path = "soil/ru_mm.tif"

Inside each SAFRAN cell the raster pixels are sorted into ten classes of equal
area, and each class is a soil column. ``ru`` stays the mean capacity of the
cells: the map only spreads it. To use the raster values as they are, write
their mean, which the soil alone prints. Classes matter: a soil computed on the
mean capacity of a heterogeneous cell recharges about 4 % less and refills
weeks later, since the recharge is a convex function of the capacity.

Comparing with SIM2
-------------------

Compare the recharge plus the sealed runoff with ``DRAINC + RUNC``, never with
``DRAINC`` alone: in soil mode the runoff of saturated ground leaves through
the drains, which ISBA counts in ``RUNC``. Compare by period. On the Nancon,
the SIM2 drainage keeps a summer floor of about 0.3 mm/day from 2016 only; in
1985-2014 its summer mean is 0.03 to 0.06 mm/day. The soil reservoir looks
like the older drainage in summer.

``components = ["total"]`` counts the snow as rain on the day it falls. The
Breton lowlands allow it; a snowy catchment does not.

What it does not do
-------------------

- It does not run under MODFLOW-NWT or Boussinesq.
- It does not couple the soil to the water table: a shallow water table does
  not reduce ``ru``. The unmet ETP drawn from the water table covers part of
  that exchange.
- It does not route direct runoff other than the sealed share. Saturation
  runoff leaves through the drains.
- It does not produce the GR4J store or a slow percolation: a slow drainage is
  what it removes.
- It does not read calendars without leap days (projections).

Choices the literature does not settle
--------------------------------------

Each is a choice, tested where a test can defend it:

- the rain reaches the soil before it evaporates, the same day (unit test;
  evaluating the stress before the rain changes the recharge by 0.4 to 1.8 %);
- all the water above ``ru`` recharges; saturation runoff is left to the
  drains;
- the soil starts from its first year repeated until it settles (unit test);
- the bypass is a constant share of the rain, zero by default;
- one exponential transit time per column, at most 30 days (unit test and
  validation case);
- the ETP the soil leaves unmet is what the water table can evaporate (the
  MODFLOW evaporation never exceeds it, integration test);
- SAFRAN cells times capacity classes, not model cells (one class gives the
  uniform soil, unit test);
- ``kc = 1`` and ``alpha = 0.6`` have no table for a mixed Breton land cover;
  they stay fixed unless a calibration lists them.

References
----------

- Allen, R.G., Pereira, L.S., Raes, D., Smith, M. (1998). Crop
  evapotranspiration. FAO Irrigation and Drainage Paper 56.
- Seibert, J., Vis, M.J.P. (2012). Teaching hydrological modeling with a
  user-friendly catchment-runoff-model software package. HESS 16, 3315-3325.
  https://doi.org/10.5194/hess-16-3315-2012
- Le Moigne, P. et al. (2020). The latest improvements with SURFEX v8.0 of the
  Safran-Isba-Modcou hydrometeorological model for France. GMD 13, 3925-3946.
  https://doi.org/10.5194/gmd-13-3925-2020
- Ireson, A.M., Butler, A.P. (2013). A critical assessment of simple recharge
  models: application to the UK Chalk. HESS 17, 2083-2096.
  https://doi.org/10.5194/hess-17-2083-2013
- Moore, R.J. (2007). The PDM rainfall-runoff model. HESS 11, 483-499.
  https://doi.org/10.5194/hess-11-483-2007
