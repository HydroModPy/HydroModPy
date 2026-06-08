Lakes and Reservoirs (MODFLOW 6 LAK)
====================================

Use the ``lake`` boundary condition when a surface water body exchanges with the
aquifer and its stage has to be solved, not prescribed. HydroModPy builds the
MODFLOW 6 LAK package from a lake declared in config: a geometry polygon, a
stage-volume-area abacus, the lake-bed leakance, and optional spillway outlets
and transient forcings. The lake stage, its volume, and the lake-aquifer
exchange (including under-dam leakage) are solved by MODFLOW 6 and extracted into
the run results store.

The ``lake`` boundary is MODFLOW 6 only. Declare the flow process with
``solvers = ["modflow6"]``.

Execution Model
---------------

A config-declared lake reaches LAK through the production pipeline:

1. ``flow.active_bc`` carries ``lake`` (or ``reservoir``), which selects the LAK
   backend package;
2. the data planner infers the ``lake_geometry`` and ``lake_abacus`` families
   from that token and the loader reads the custom polygon and abacus table;
3. the mesh build intersects the lake polygon with the grid to find the lake
   cells;
4. the LAK package is written from the ``flow.sinks_sources.lakes.<id>`` payload,
   the abacus (as a laktab table), the outlets, and the forcings;
5. MODFLOW 6 solves the lake stage and the lake-aquifer exchange;
6. the lake observation output is parsed into per-lake series keyed
   ``lake:<id>`` in the results store.

The lake stage is a solved state. It responds to the aquifer head, the abacus
bathymetry, the outlets, and the forcings together. It is not a prescribed level.

Declaring a Lake
----------------

A lake needs three things in config: the ``lake`` token in ``flow.active_bc``, a
``flow.sinks_sources.lakes.<id>`` payload with ``bedleak`` and ``stageinit``, and
the custom data sources for the geometry polygon and the stage-volume-area
abacus. This is the working pattern exercised by the lake end-to-end test.

.. code-block:: toml

   [flow]
   flow_regime = "transient"
   active_sinks_sources = ["recharge"]
   active_bc = ["lake", "drainage"]
   param_list = ["K", "Ss", "Sy"]

   [flow.sinks_sources.lakes.lac0]
   bedleak = 0.1
   stageinit = "101.0 m"

   [[flow.sinks_sources.lakes.lac0.outlets]]
   couttype = "WEIR"
   invert = "104.0 m"
   width = "5.0 m"
   lakeout = 0

   [[data.lake_geometry.sources]]
   source = "custom"
   path = "data/lake_geometry/lac0.gpkg"

   [[data.lake_abacus.sources]]
   source = "custom"
   path = "data/lake_abacus/lac0.csv"
   lake_id = "lac0"

``bedleak`` is the lake-bed leakance (1/T): the resistance of the lake-aquifer
interface, and the calibration handle for under-dam leakage. ``stageinit`` is the
initial stage. The geometry source is a polygon (SHP, GPKG, or GeoJSON) in the
project CRS. The abacus source is a CSV with ``stage,volume,sarea`` columns that
brackets the operating range of the stage; ``lake_id`` ties the abacus to the
matching lake id.

The lake payload accepts these fields.

.. list-table::
   :header-rows: 1
   :widths: 22 18 60

   * - Field
     - Units
     - Meaning
   * - ``bedleak``
     - 1/T
     - Lake-bed leakance, the lake-aquifer interface resistance. Required.
   * - ``stageinit``
     - L
     - Initial lake stage. Required.
   * - ``outlets``
     - --
     - Array of spillway / controlled-release outlets. Optional.
   * - ``rainfall``
     - L/T
     - Rainfall rate over the lake surface. Optional forcing.
   * - ``evaporation``
     - L/T
     - Open-water evaporation rate. Optional forcing.
   * - ``runoff``
     - L^3/T
     - Lateral runoff into the lake. Optional forcing.
   * - ``inflow``
     - L^3/T
     - Specified inflow into the lake. Optional forcing.
   * - ``withdrawal``
     - L^3/T
     - Abstraction from the lake (signed negative). Optional forcing.

Spillways and Outlets
---------------------

Outlets are an array of tables discriminated by ``couttype``. They drain the lake
once the stage rises above the configured invert and route the discharge either
out of the model or into a downstream lake.

A weir spillway has a fixed crest. The lake discharges once the stage rises above
``invert``; ``width`` is the effective crest length.

.. code-block:: toml

   [[flow.sinks_sources.lakes.lac0.outlets]]
   couttype = "WEIR"
   invert = "104.0 m"
   width = "5.0 m"
   lakeout = 0

A Manning outlet adds a roughness coefficient and a bed slope for a rated
channel.

.. code-block:: toml

   [[flow.sinks_sources.lakes.lac0.outlets]]
   couttype = "MANNING"
   invert = "104.0 m"
   width = "5.0 m"
   rough = 0.03
   slope = 0.001
   lakeout = 0

A specified outlet is a controlled release: a gate or a managed discharge. The
``rate`` is volumetric and signed (positive in, negative out). Use a transient
``forcing`` instead of a constant ``rate`` for a scheduled release.

.. code-block:: toml

   [[flow.sinks_sources.lakes.lac0.outlets]]
   couttype = "SPECIFIED"
   rate = "-0.02 m^3/s"
   lakeout = 0

``lakeout = 0`` sends the outlet discharge to an external boundary, out of the
model. A positive integer routes the discharge directly to that downstream lake
(1-based). For a cascade between two lakes (a pre-reservoir feeding a main
reservoir), keep ``lakeout = 0`` and add a ``mover`` block on the outlet: the LAK
outlet then feeds a MODFLOW 6 MVR record routed to the receiving lake, which lets
you transfer a fraction (``FACTOR``), a capped flow (``UPTO``), only the excess
above a value (``EXCESS``), or an all-or-nothing threshold (``THRESHOLD``).

.. code-block:: toml

   [flow.sinks_sources.lakes.lac_upper]
   bedleak = 0.1
   stageinit = "120.0 m"

   [[flow.sinks_sources.lakes.lac_upper.outlets]]
   couttype = "WEIR"
   invert = "121.0 m"
   width = "8.0 m"
   lakeout = 0

   [flow.sinks_sources.lakes.lac_upper.outlets.mover]
   lake = 2
   mvrtype = "FACTOR"
   value = 1.0

   [flow.sinks_sources.lakes.lac0]
   bedleak = 0.1
   stageinit = "101.0 m"

An outlet sets either ``lakeout`` or a ``mover``, never both. ``lake = 2`` is the
1-based number of the receiving lake in declaration order.

Forcings
--------

Rainfall and evaporation are rates (L/T) applied over the lake surface. Runoff,
inflow, and withdrawal are volumetric (L^3/T). Each forcing is one of four kinds:
``constant``, ``csv``, ``piecewise``, or ``seasonal``.

A constant rate forcing carries a bare numeric value plus the source ``units``
the runtime converts from.

.. code-block:: toml

   [flow.sinks_sources.lakes.lac0.rainfall]
   kind = "constant"
   value = 2.0e-8
   units = "m/s"

   [flow.sinks_sources.lakes.lac0.evaporation]
   kind = "constant"
   value = 5.0e-8
   units = "m/s"

A piecewise forcing covers the simulation window with date-ordered segments, each
resolved by its own constant or CSV sub-forcing. This reads a CSV chronicle until
a date, then holds a constant value afterwards.

.. code-block:: toml

   [flow.sinks_sources.lakes.lac0.inflow]
   kind = "piecewise"
   units = "m3/s"

   [[flow.sinks_sources.lakes.lac0.inflow.segments]]
   start = "2003-01-01"
   end = "2003-07-01"
   forcing = { kind = "csv", path_file = "data/inflow.csv", value_column = "q" }

   [[flow.sinks_sources.lakes.lac0.inflow.segments]]
   start = "2003-07-01"
   forcing = { kind = "constant", value = "0.1 m^3/s" }

A seasonal forcing repeats a calendar mapping across years. Use ``by_season``
with the four meteorological seasons, or ``by_month`` with all twelve months.

.. code-block:: toml

   [flow.sinks_sources.lakes.lac0.withdrawal]
   kind = "seasonal"
   units = "m3/s"
   by_season = { DJF = -0.01, MAM = -0.03, JJA = -0.05, SON = -0.02 }

Segments must be strictly date-ordered and non-overlapping; a seasonal mapping
must be complete (all four seasons or all twelve months). Long chronicles are
written to a MODFLOW 6 time-series (TS6) file automatically, so a forcing of any
length stays out of the stress-period lists.

Running
-------

Run a lake project with the same command as any other simulation.

.. code-block:: bash

   hmp run reservoir_run.toml

MODFLOW 6 runs through the ``mf6`` executable by default (the subprocess runner).
A developer can opt into the in-process libmf6 runner, which drives the same
simulation through the API. The choice is set in TOML and changes nothing in the
written model or the extracted outputs.

.. code-block:: toml

   [modflow6.runtime]
   mf6_runner = "subprocess"

.. code-block:: toml

   [modflow6.runtime]
   mf6_runner = "api"

Both runners write the same simulation and produce the same lake series, so
switch runner only to gain in-process callback access, not to change results.

Python
------

The high-level entry point runs a project from its config and returns a result
handle.

.. code-block:: python

   import hydromodpy as hmp

   result = hmp.run("reservoir_run.toml")

For programmatic control, drive the lifecycle through the ``Project`` facade.

.. code-block:: python

   import hydromodpy as hmp

   with hmp.Project("reservoir_run.toml") as project:
       project.prepare()
       run = project.simulate()

The libmf6 API runner is the developer path that observes a lake while it solves.
The model must be written first, then ``run_api`` drives it through libmf6 with a
per-step callback. Read the solved lake stage at the end of each timestep.

.. code-block:: python

   from hydromodpy.solver.modflow6.api_runner import Mf6ApiContext, Mf6ApiStep

   def on_step(ctx: Mf6ApiContext) -> None:
       if ctx.step is Mf6ApiStep.timestep_end:
           stage = ctx.read_lake_stage()
           print(ctx.kper, ctx.kstp, ctx.totim, stage)

   success = model.run_api(on_step)

``read_lake_stage()`` returns the solved per-lake stage as a 1-D array (the same
value MODFLOW 6 saves), and ``ctx.read_heads()`` returns the aquifer heads.
``write_lake_stage(values)`` overrides the input starting stage, but the lake
stage is an aquifer-driven equilibrium: writing it forces only the current
solution and the model relaxes back. To hold a lake level, change a boundary
instead (raise the weir ``invert``, or use a ``SPECIFIED`` outlet). The API
runner needs the optional ``modflowapi`` and ``xmipy`` packages; install them with
``pip install modflowapi xmipy``.

Outputs
-------

Per-lake series are stored under the ``lake:<id>`` station id in the results
store, keyed by simulation time. Read one with
``store.query_timeseries(sim_id, "lake:lac0", "<quantity>")``.

.. list-table::
   :header-rows: 1
   :widths: 26 18 56

   * - Quantity
     - Units
     - Meaning
   * - ``stage``
     - L
     - Solved lake stage.
   * - ``volume``
     - L^3
     - Lake volume from the abacus.
   * - ``surface_area``
     - L^2
     - Lake surface area from the abacus.
   * - ``gwf_exchange``
     - L^3/T
     - Total lake-aquifer exchange (negative = lake losing water).
   * - ``seepage_under_dam``
     - L^3/T
     - Under-dam leakage, the vertical connections summed separately.
   * - ``ext_outflow``
     - L^3/T
     - Discharge leaving through the outlets.
   * - ``inflow``, ``runoff``, ``rainfall``, ``evaporation``, ``withdrawal``
     - L^3/T or L/T
     - The applied forcing terms of the lake water balance.

The spatially resolved per-cell lake seepage (the GWF cell-by-cell ``LAK`` budget
record) is stored separately under ``budget/lak`` in the run Zarr store, so the
seepage footprint can be mapped over the aquifer, not just summed per lake.

The executable reference for this guide is the lake end-to-end test
``tests/e2e/test_lake_project_e2e.py``: it writes a synthetic lake polygon and
stage-volume-area abacus, runs the same pipeline as ``hmp run`` on the committed
``examples/data/dem/regional_dem_naizin.tif`` catchment, and asserts the LAK
package, the lake stage series, and the lake-aquifer exchange.

References
----------

- MODFLOW 6 LAK package: https://modflow6.readthedocs.io/en/stable/_mf6io/gwf-lak.html
- MODFLOW 6 MVR water mover: https://modflow6.readthedocs.io/en/stable/_mf6io/gwf-mvr.html
- MODFLOW 6 time series (TS6): https://modflow6.readthedocs.io/en/stable/_mf6io/timeseries.html
- MODFLOW 6 releases: https://github.com/MODFLOW-USGS/modflow6/releases
