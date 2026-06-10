Streams and Routing (MODFLOW 6 SFR)
===================================

Use the ``sfr`` boundary condition when streamflow has to be routed through an
explicit reach network: headwater inflow and distributed runoff travel
downstream, each reach exchanges with the aquifer through its streambed, and
the accumulated flow either leaves the model at the network outlet or feeds a
lake. HydroModPy delineates the network from the DEM-derived river products,
splits each stream link onto the DISV mesh, and writes the MODFLOW 6 SFR
package with downstream-increasing reach numbering.

The ``sfr`` boundary is MODFLOW 6 only. Declare the flow process with
``solvers = ["modflow6"]``.

Execution Model
---------------

A config-declared network reaches SFR through the production pipeline:

1. ``flow.active_bc`` carries ``sfr``, which selects the SFR backend package;
2. the geographic preprocessing builds the river-network products
   (``[geographic.river_network]`` with ``compute_stream_links = true``, and
   ``compute_strahler_order = true`` when a width-by-order law is used);
3. the delineation turns the full-grid stream-link raster, the D8 pointer, the
   flow accumulation and the corrected DEM into an ordered reach trace
   (one polyline per link, reciprocal connectivity, monotone-downhill streambed
   tops); a link entering a lake footprint is truncated at the shoreline and
   flagged terminal;
4. the solver builder intersects each polyline with the DISV mesh
   (order-preserving), splits it into per-cell sub-reaches, re-numbers the
   post-split network downstream-increasing, and writes PACKAGEDATA, the signed
   CONNECTIONDATA and the PERIOD forcings;
5. the DRN entries coincident with reach cells are removed, so catchment
   baseflow discharges into the stream instead of leaving the model;
6. MODFLOW 6 routes the streamflow; per-reach series land in the results store
   keyed ``sfr:<network>:<reach>``.

Standalone Network
------------------

A network with ``outflow_to_lake`` unset routes streamflow with no lake at all:
the terminal reach's outflow leaves the model and is reported as
``ext_outflow``. This is the setup for streamflow studies (low flows,
intermittency): the per-reach ``downstream_flow`` chronicle is the simulated
discharge along the network, and a reach whose flow falls to zero is a drying
reach.

.. code-block:: toml

   [geographic.river_network]
   enabled = true
   threshold_mode = "area_km2"
   threshold_area_km2 = 0.1
   compute_stream_links = true
   compute_strahler_order = true

   [flow]
   active_bc = ["sfr", "drainage"]

   [flow.sinks_sources.sfr.net0]
   stream_threshold_km2 = 0.1
   streambed_k = 1e-5
   streambed_k_unit = "m/s"
   streambed_thickness = "1 m"
   manning = 0.035

   [flow.sinks_sources.sfr.net0.width]
   kind = "constant"
   value = "2 m"

The network stream threshold must resolve to the same cell count as the
``geographic.river_network`` threshold: the v1 delineation reuses that link
raster as the single stream-geometry source and raises on a mismatch.

The reach width law is a discriminated union: ``constant`` (uniform width),
``by_order`` (one width per Strahler order) or ``power_law``
(``width = coef * drainage_area_km2 ** exp``).

Catchment streamflow generation
-------------------------------

Two mechanisms feed the network beyond its own streambed exchange:

* ``route_drainage = true`` converges the hillslope drainage into the network:
  every remaining DRN cell (the seepage outlets away from the stream) hands its
  discharge to the NEAREST reach through an MVR record, so the drained water
  travels down the river instead of leaving the model. Without it only the
  reach cells' streambed captures baseflow and most of the catchment discharge
  is lost; with it the reach ``downstream_flow`` is the actual catchment
  streamflow. It requires a static (single-period) drain, because the MVR
  provider ids index the DRN boundary list.
* the ``runoff`` data family (previous section) adds the overland flow.

For realistic discharge chronicles, and hence for intermittency mapping,
enable both.

Feeding a Lake (SFR -> LAK through MVR)
---------------------------------------

Set ``outflow_to_lake`` to the 1-based lake number and the terminal reach hands
its accumulated flow to the lake through a water-mover (MVR) record. This is
how a reservoir is fed by its catchment streamflow: the baseflow captured along
the reaches plus the routed runoff arrive as the lake's ``from_mvr`` series.

.. code-block:: toml

   [flow]
   active_bc = ["lake", "sfr", "drainage"]

   [flow.sinks_sources.sfr.net0]
   stream_threshold_km2 = 0.1
   outflow_to_lake = 1

   [flow.sinks_sources.sfr.net0.runoff]
   kind = "constant"
   value = 0.002
   units = "m3/s"

The symmetric direction exists for a spillway release: a lake outlet whose
``mover`` carries ``reach`` (instead of ``lake``) routes its discharge to the
given downstream reach.

Forcings and Units
------------------

``headwater_inflow`` and ``runoff`` are volumetric (``m3/s``); the runoff is
distributed over the reaches by length fraction and the inflow lands on the
headwater reaches split by drainage area. ``rainfall`` and ``evaporation`` are
rates (``m/s``) applied per reach. Non-constant forcings follow the shared
TS6-versus-inline arbitration used by the lake package. ``streambed_k`` declares
its unit through ``streambed_k_unit`` and reaches MF6 in ``m/s``.

When the ``runoff`` data family is loaded (e.g. SIM2), an active SFR network
takes it automatically: the watershed-mean rate times the catchment area becomes
the routed ``runoff`` forcing, and the lake's legacy direct ``runoff * area``
feed is skipped so the same water is never counted twice. Without SFR the
runoff feeds the lake directly, as before. A ``runoff`` forcing declared in the
network config always wins over the data family.

Results and Display
-------------------

Per-reach series are stored under ``station_id = sfr:<network>:<reach>``:
``stage`` and ``depth`` in meters; ``downstream_flow``, ``ext_inflow``,
``ext_outflow``, ``gw_exchange``, ``to_mvr`` and ``from_mvr`` in ``m3/s``.
Outflow-side terms are stored as positive flows and ``gw_exchange`` is positive
when the reach gains baseflow from the aquifer.

Three figures read those series from the store: ``sfr_reach_timeseries`` (one
quantity on one reach), ``sfr_longitudinal_profile`` (one quantity across the
reach numbering at a chosen time step) and ``sfr_reach_network`` (the
delineated network map annotated with the routed state).

Validation
----------

``validation_cases/numerical/transient/sfr_lak_mvr`` reproduces the upstream
MODFLOW 6 example ``ex-gwf-lak-p02`` (Merritt & Konikow 2000: two lakes, a
22-reach SFR network and four MVR transfers) and matches the published
converged stages within the documented tolerances.
