Calibrating on the stream network
=================================

How to calibrate a catchment against the extent of its hydrographic network
rather than against a gauge, in two stages: the transmissivity-to-recharge
ratio against the network in steady state, then the storage against the
discharge in transient.

Read :doc:`../../theory/streams_and_seepage/downslope-distance-calibration`
first. This page says how to run it; that one says what the number means, and
which way each of its known biases points.

Before you start
----------------

Four things have to be true, and the first is the one people skip.

**The mapped network must sit in the talwegs of the routing surface.** The
criterion measures lengths along the flow paths of the DEM, so if the linework
does not follow them, it measures a disagreement between two datasets. Burn the
network into the routing surface first:

.. code-block:: toml

   [geographic.enforce_streams]
   enabled = true
   stream_geometry_path = "data/hydrography/streams.gpkg"
   mode = "constant"
   depth_m = 30

The burn needs a network, and it needs it as a file: it runs inside the
geographic step, before any data manager, so it cannot read what the data
loading step later produces. ``stream_geometry_path`` says which file, and it is
anchored once, when the configuration is loaded: a relative value against the
directory of the TOML that declares it, a bare filename under
``<workspace>/data/hydrography/`` then ``<workspace>/data/``. Nothing is probed
when the file is read, so the run takes the same network whatever directory it
was launched from.

Leave it out and the burn falls back to what ``[[data.hydrography.sources]]``
declares, so the same file is named once:

.. code-block:: toml

   [[data.hydrography.sources]]
   source = "custom"
   path = "streams.gpkg"

   [geographic.enforce_streams]
   enabled = true
   mode = "constant"
   depth_m = 30

A ``custom`` source hands its own file straight over, a directory yields its
first vector layer, and a raster one yields nothing: the burn rasterizes
geometries onto the DEM grid itself. An API source (``osm``, ``bdtopage``,
``euhydro``) is downloaded on a box around ``x_outlet`` / ``y_outlet``, clipped
to the DEM footprint, and cached under ``<workspace>/data/hydrography/``; the
watershed a data manager would clip against is not delineated yet at that point,
and the regional extent is what the burn wants anyway. Declaring
``stream_geometry_path`` explicitly always wins, which is how you burn a network
that differs from the one the data family loads. Declaring neither stops the
geographic pipeline at the first step, before anything is calibrated.

A project declaring that path gets the agreement measured whether or not
``enabled`` is set, which is how you find out that the burning is needed. It
goes to ``stream_dem_agreement.json`` in the geographic directory, as
``alpha``: the ratio between the mapped network and its own downslope closure,
where one means the linework follows the talwegs and below 0.90 the run warns.
Redo the burning at every change of resolution: the ratio between the width of
the linework and the cell size changes with it.

**That number is not the one the criterion publishes, and the two cannot
agree.** The burn is cut into the routing DEM alone; the model top stays on the
raw DEM, because a top lowered along the mapped network would give a model that
seeps along it by construction. The criterion measures its distances on that
top, so the ratio it recomputes on the solver mesh and publishes per trial as
``alpha_obs_closure`` describes a different surface. On the Nancon the routing
DEM reaches ``alpha = 0.994`` after a 30 m burn while ``alpha_obs_closure``
sat at 0.306, and ``alpha_obs_closure_catchment`` at 0.693, when one outlet
sealed the whole mesh. With the flood seeded on the domain border the buffer
reaches leave through the border, and the first two come close (0.81 and 0.77
on a 75 m proxy of the same basin). Read the three:
the first says the delineation and the flow paths follow the map, the third
says how much of the criterion's own measurement is a top-versus-map
disagreement, and the gap between the second and the third is the mapped
linework the criterion carries outside the basin. **A trial is judged on the
third.** The criterion never descends the burned surface, so a low value there
is never a reason to burn deeper.

**The drain conductance must stay proportional to the conductivity.** Leave
``[flow.bc.cauchy.drainage] value`` at zero, or at anything not strictly
positive, so the fallback applies: ``C = K * cell_area / solver.drain_bed_thickness_m``
on both MODFLOW backends (the clogging-layer thickness of a watercourse,
decimetres to a metre, not the model layer thickness), ``C = K * cell_area`` on
Boussinesq. That proportionality is
what makes the ratio the calibrated quantity; a fixed conductance breaks the
invariance from a factor 1.05 onwards.

**The recharge must be frozen during the first stage.** The criterion at one
per cent is on the ratio, which equals one per cent on the conductivity only
when the recharge does not move. Every trial publishes ``R_mean_m_s``, the mean
recharge the criterion actually read back from the built model, and a move
between two builds raises a warning naming both values. Nothing refuses the run,
because this check knows a mesh and not a session: keep the recharge out of
``[calibration.parameters]`` and out of anything the first phase moves, and read
``R_mean_m_s`` across the trials before reading the calibrated value as a ``K``.

**The union has to cover every package that carries water out of the aquifer.**
The criterion reads the per-cell release as the union of the packages that can
feed the surface: drains, streams, release-role constant heads. Whenever the
stream reaches are modelled rather than drained, most of the seepage leaves
through the stream package and not through the drain. Measured on the Nancon
with the main reaches in SFR: the aquifer sent 1.33 of its 2.10 m3/s through
the stream package while 0.80 stayed on the drain. A union reading the drain
alone would report 63 per cent of that water as dry land, exactly where the
package drains, which is exactly where the criterion aims. Both extractors now
read the requirement off the budget file rather than off the model object, and
refuse a release record no declared package covers instead of returning a
partial network.

The visible symptom, if that guard is ever bypassed, is a root that stops
responding to the parameter: on that same run the search closed on a
conductivity three decades above its declared bounds, with a validity indicator
comfortably inside its own. A simulated network holding its cells by
construction never retracts, and the criterion then balances against a fixed
skeleton.

Snapping the mapped network
---------------------------

Burning conditions the *routing surface* so its D8 paths follow the mapped
network; it never moves the map. ``[geographic.snap_streams]`` does the
opposite: it moves the map, cell by cell, onto the talwegs the criterion
graph already carries, and publishes what the move cost. The two repairs
answer different questions and neither replaces the other: a network burned
into the routing raster can still sit off the mesh's own talwegs once the
mesh floods that raster back (see "Before you start" above), and a snapped
map still measures a genuine hydrogeological disagreement wherever it was
never off-talweg to begin with.

Off by default, three modes:

.. code-block:: toml

   [geographic.snap_streams]
   mode = "diagnose"
   radius = "2 cells"
   max_displacement_p90 = "1 cell"
   max_rejected_share = 0.10

``off``
   Computes nothing. Every trial publishes exactly what it published before
   the snap existed.
``diagnose``
   Computes the snapped map, its displacement, its rejected cells, the length
   change and the floor ``F`` (below), and publishes them — but still scores
   the **raw** map, so nothing about the calibrated value changes.
``apply``
   Scores the **snapped** map. Equation 4 then also asks the 90th percentile
   of the displacement and the share of rejected cells to stay within their
   bounds, on top of ``Doptim <= validity_length``.

``radius`` and ``max_displacement_p90`` are lengths: a Pint length such as
``"200 m"``, or a count of cells such as ``"2 cells"`` — one cell being
``h_obs`` (below), so the same TOML means the same number of mesh cells at
every resolution. Two cells is the outlet-snapping distance of the paper's
own ``SnapPourPoints``. It sits under ``[geographic]``, beside
``enforce_streams``, because it is common to every consumer of the mapped
network — the criterion, the redrawn figures, and (not wired yet, see
below) stream burning — not to one calibration output.

The algorithm
   Flow-accumulation guided snapping, run on the same graph the criterion
   descends, in the topological order of the mapped network from downstream
   to upstream:

   1. the mapped cells of the catchment are grouped into connected pieces on
      the criterion's neighbour graph, each piece rooted at its lowest cell;
   2. the pieces are walked by a priority flood along the map itself, most
      accumulated first, so a main stem is processed before the tributaries
      that join it;
   3. each mapped cell moves, within the radius, to the free model cell with
      the highest accumulation whose receiver is already attached — the
      outlet and the water bodies are attached from the start — which is
      what keeps every snapped cell continuous to the outlet;
   4. a cell with no such candidate merges onto the nearest attached cell
      within the radius instead, counted as merged; with neither, it is
      rejected and keeps its raw position, so a grossly misplaced reach stays
      visible to Equation 4 rather than disappearing into a plausible number;
   5. a talweg cell no mapped cell moved onto is never added: a gap in the
      map is not bridged, the reach above it attaches one cell lower, and the
      displacement says so.

   Mapped cells outside the catchment are not scored and are left as they are.

Limits, read before trusting an ``apply`` run
   A gap in the map drags the whole reach above it down by one cell, and the
   displacement map shows it. A map that never comes within one radius of the
   outlet, and never joins a piece that is already attached, is rejected
   whole rather than partly. On tortuous talwegs a few per cent of cells are
   rejected even on a well-registered map — 5 to 6 % measured on a noisy
   synthetic network shifted by one column — so a nonzero ``snap_rejected_share``
   is not by itself evidence of a bad map. A radius of two cells can also
   reach into a neighbouring, more accumulated talweg and pull the map onto
   the wrong branch; watch ``snap_accumulation_percentile_p50`` and the map
   figure below for that.

   **``apply`` changes what is scored, and that is a risk as much as a fix.**
   ``roptim`` in ``apply`` mode measures the agreement between the model and
   the *snapped* map, not the surveyed one, so a badly registered map that
   ``diagnose`` would have flagged with a large ``snap_displacement_p90_m``
   can come back looking well calibrated once it is moved onto the model's
   own talwegs. Run ``diagnose`` first, read the displacement histogram and
   ``snap_floor_m``, and only turn ``apply`` on once the displacement is
   small relative to the positional accuracy of the source: a large snap is a
   sign the DEM and the map disagree structurally, which burning or a better
   DEM should fix, not a distance the snap should absorb silently.

Published indices
   Every trial with ``mode != "off"`` publishes, per output (and per bound,
   suffixed, when two maps are scored): ``snap_mode`` (1 for ``diagnose``, 2
   for ``apply``), ``snap_radius_m``, ``snap_displacement_p50_m``,
   ``snap_displacement_p90_m``, ``snap_displacement_bound_m``,
   ``snap_rejected_share``, ``snap_rejected_share_max``, ``snap_moved_share``,
   ``snap_merged_share``, ``snap_length_ratio``, ``snap_connected_share``,
   ``snap_accumulation_percentile_p50``, ``snap_n_cells_raw`` and
   ``snap_floor_m``.

   ``snap_floor_m`` is ``F``, the ``Doptim`` a model that reproduced the
   snapped talwegs *exactly* would still score against the raw map, computed
   with the criterion's own metric, sealed outlet and per-cell weighting. It
   is the representation error the snap itself introduces: no calibrated
   value can read as more accurate than ``F``, whatever ``roptim`` says.

Equation 4 in ``apply`` mode
   The verdict now reads three conditions together: ``Doptim <=
   validity_length`` on the snapped map, the 90th percentile of the
   displacement at or under ``max_displacement_p90``, and the rejected share
   at or under ``max_rejected_share``. In ``diagnose`` mode the verdict still
   reads ``Doptim`` on the raw map, because the raw map is what was scored;
   the floor ``F`` only widens the validity length (below). The report names
   the cause of a failure: the mismatch, the snap, or both.

``h_obs`` replaces the reference length
   ``L_ref``, the length ``roptim`` and the width of a network output's
   search interval are read against, is ``h_obs``: the median distance
   between the centres of neighbouring cells that share an edge, taken over
   the mapped cells of the catchment (or, absent any, the catchment itself).
   It replaces the square root of the median cell area, so on a regular grid
   nothing changes — both read the cell size — but on a mesh refined along
   the streams the old measure could land on the coarse hillslope cells a
   catchment-wide median happens to pick, while ``h_obs`` reads the scale
   where the mapped network actually sits, the fine cells.
   ``observed_position_accuracy`` no longer touches it: ``roptim`` is
   ``Doptim / h_obs``, the paper's Equation 3, whatever the output declares.
   It is read on the **raw** map, even in ``apply`` mode: the radius the snap
   searches within is counted in the resolution the map was captured at, not
   in the resolution it was moved onto. ``<output>.cell_spacing_m`` carries
   the same value.

The validity length
   Equation 4 is a length in metres: the calibration is valid when ``Doptim
   <= validity_length``. ``validity_length = "auto"``, the default, reads a
   cell size ``h``, which is ``h_obs``, raised to
   ``observed_position_accuracy`` when the output declares one, and then:

   - without the snap, ``2 h``: the paper's two pixels, so ``roptim <= 2``
     on a regular grid;
   - with ``[geographic.snap_streams]`` in ``diagnose`` or ``apply``,
     ``h + max(h, F)``: one cell for the hydrogeology, and one for the map
     error the paper budgets (HESS p. 3224), replaced by the floor ``F``
     when ``F`` is larger. At 75 m on the Nançon ``F`` stays under one cell
     and the bound is the paper's 150 m; at 25 m it is about three cells and
     the bound widens to about 100 m instead of 50 m.

   A length such as ``validity_length = "300 m"`` replaces the computation.
   Each map resolves its own length, so the two bounds of the two-bound mode
   may differ. Every trial publishes ``validity_length_m`` and
   ``validity_length_provenance``, a code: 0 ``auto`` (two cells), 1
   ``auto_floor`` (``F`` exceeded ``h``), 2 ``declared_accuracy`` (the
   declared accuracy exceeded ``h_obs``), 3 ``user`` (a declared length).
   The former ``roptim_max`` is gone. ``hmp doctor --fix-config`` drops it
   from a file that sets it to 2, which ``"auto"`` reproduces, and refuses
   any other value with the length to write instead. ``hmp calibrate`` and
   ``hmp run`` apply the same migration in memory when they read the file,
   without rewriting it.

Scope
   The setting applies to every consumer of the mapped network. ``apply``
   makes each one read the snapped map, ``diagnose`` leaves each one on the
   raw map while the snap is computed and published, and ``off`` changes
   nothing anywhere.

   - The criterion (every network output, one map or two) and its figures
     snap on the criterion graph of the mesh.
   - A run stores the snapped map it scored as a geographic feature (one
     point per mapped cell of the catchment, with its displacement, status
     and accumulation percentile). The overlap and distance metrics of the
     ``reference`` and ``reference_permanent`` roles read it in ``apply``,
     and say which map they read under ``network_map``.
   - ``[geographic.enforce_streams]`` burns the routing raster before any
     mesh exists, so its snap runs on the raster grid: the raw DEM is
     conditioned by ``dem_correc_type``, the rasterised map is snapped on the
     eight-neighbour graph of that raster by the same algorithm and radius
     rule, and ``apply`` burns the snapped cells instead of the raw lines.
     The routing DEM is then conditioned again as usual. This pass runs
     whenever the snap is on and ``enforce_streams.stream_geometry_path``
     names a network, burning or not, and costs one extra conditioning pass
     and a graph over the whole raster.
   - That raster pass is published in the geographic directory:
     ``stream_snap_raster.json`` (mode, mapped file, indices),
     ``stream_snap_raster.tif`` (snapped map, per-cell status) and
     ``stream_snap_raster_lines.gpkg``. A mesh whose ``rivers.source =
     "file"`` names the same mapped file reads those lines in ``apply``, and
     the stream/DEM agreement of the geographic step measures the snapped
     map the burn followed.

Two figures read the sealed setting of the run they were asked to draw, so an
``apply`` run's figures show the snapped map it scored, never the raw one:

``observed_network_snap_map``
   The raw mapped cells outlined, the snapped map filled, and one segment per
   raw cell joining it to where it moved, coloured by its status
   (unchanged, moved, merged, rejected).
``observed_network_snap_histogram``
   The displacement, stacked by status, with the ``max_displacement_p90``
   bound and the search radius drawn as lines, and the rejected count in the
   key rather than left out of the picture.

Both refuse by name, with a sentence instead of a figure, on a run whose
``[geographic.snap_streams]`` is ``off``.

Naming the method
-----------------

The two stages, their criteria, and the regime that makes one steady and the
other transient are the method, not the site. Name it and they are written
for you:

.. code-block:: toml

   [calibration]
   protocol = "matching_hydrographic_network"

The section name is the quantity: ``K`` is the id this project declares in
``[flow].param_list``, and it is resolved against what the project exposes, so
neither the path into the configuration nor the log space a conductivity is
searched in has to be written. ``hmp config targets`` prints the names a given
project carries. Writing ``path`` is still allowed and still wins, for a value
the catalogue does not reach.

What stays in the file is the two search ranges and the mapped network.
:doc:`calibration-recipes` shows the whole thing, with every option written out
and its default explained. The engines are free: ``steady_method`` and
``transient_method`` take any registered optimizer, so the same two criteria can
be walked by a bisection, by Nelder-Mead or by Optuna without changing what is
calibrated. The run records the method and its citation, so a value that came
out of it says what it rests on.

A file cannot both name a protocol and declare phases or objective blocks of
its own. That is two answers to one question, and it is refused rather than
silently resolved, naming the section it found them in. Stages identical to
the ones the protocol would write are the exception, and not a loophole: it is
how a run re-read from its own sealed configuration replays. A child
inheriting a parent that names a protocol drops the name with
``protocol__delete = true`` under ``[calibration]``.

``storage`` names the parameter stage two moves, and defaults to ``Sy``, not
to network-only: the network stage alone is a method in its own right, HESS
2023 with no discharge record, but TOML has no null to ask for it with
``[calibration.protocol] storage = ...``. From a file, get the same result by
not naming the protocol at all and writing the single steady stage by hand,
the first half of "Declaring the two stages by hand" below, with no second
``[[calibration.phases]]`` table. From Python, ``storage=None`` in the options
dict still expands through the named protocol, with its citation, version pin
and declared deviations.

Declaring the two stages by hand
--------------------------------

The long form, for a variant the protocol does not cover.

.. code-block:: toml

   base_config = "project.toml"

   [workflow]
   mode = "calibration"

   [calibration]
   seed = 42
   save_runs = "best_n"
   save_best_n = 1
   persist_iteration_detail = "full"

   [calibration.parameters.K]
   bounds = [1e-9, 1e-3]

   [calibration.parameters.Sy]
   bounds = [1e-3, 3e-1]

   [calibration.outputs.seepage_network]
   support             = "network"
   stream_geometry_path = "data/hydrography/streams.gpkg"
   weighting           = "area"
   tau_specific_ratio  = 1.0e-4
   validity_length     = "auto"
   time                = "last"

   [[calibration.objective_blocks]]
   name         = "abherve_gap"
   metric       = "distance_gap"
   uses_outputs = ["seepage_network"]

   [[calibration.phases]]
   name              = "steady_conductivity"
   description       = "Zero of the signed gap D_so - D_os, by bisection on K."
   method            = "bisection"
   max_iter          = 18
   parameters        = ["K"]
   objective_blocks  = ["abherve_gap"]
   freeze_on_success = true

   [calibration.phases.method_options]
   rel_tol      = 0.01
   sweep_points = 7

   [calibration.phases.overrides]
   "flow.flow_regime"                = "steady"
   "simulation.time.start_datetime"  = "2012-01-01"
   "simulation.time.end_datetime"    = "2012-12-31"
   "simulation.time.step_unit"       = "year"
   "simulation.time.step_value"      = 1

   [[calibration.phases]]
   name       = "transient_storage"
   method     = "grid"
   max_iter   = 9
   parallel   = 4
   parameters = ["Sy"]
   variable   = "discharge"
   objective  = "nse_log"
   depends_on = "steady_conductivity"

   [calibration.phases.scoring_window]
   start = "2012-01-01"
   end   = "2015-12-31"

   [calibration.phases.method_options]
   points_per_dim = 9

   [calibration.phases.overrides]
   "flow.flow_regime"                = "transient"
   "simulation.time.start_datetime"  = "2011-01-01"
   "simulation.time.end_datetime"    = "2015-12-31"
   "simulation.time.step_unit"       = "month"
   "simulation.time.step_value"      = 1

Declaring the ``[[calibration.phases]]`` table is what switches the runner to
staged mode. Without it nothing changes for an existing configuration.

The shipped version of that file is
``examples/projects/04_streamflow_intermittence_in_transient/run_calibration_by_hand.toml``.
It inherits the project next door, which declares no calibration, and
writes the two stages as phases.

Run ``hmp calibrate run_calibration.toml --list-phases`` in that directory and
the two stages the name expands to are the two stages that file writes out. Nothing
downstream can tell them apart: the runner records ``phase_name`` and
``phase_index`` from the declarations whichever way they were written, and the
four calibration figures read those records rather than the protocol. What the
name still carries is the citation, the version pin and the list of deviations
from the publication, which a hand-written assembly records nothing of.

Scoring the second stage on two criteria
----------------------------------------

The reason to write the long form is the variant the name cannot express. The
published method scores the storage stage on the hydrograph alone; this scores
it on the hydrograph and on the extent of the simulated network, as two blocks
in one phase, each with its own share of the cost.

.. code-block:: toml

   [calibration.outputs.gauged_discharge]
   support  = "point"
   variable = "discharge"
   observes = "NANCON"

   [[calibration.objective_blocks]]
   name           = "network_extension"
   metric         = "distance_gap"
   uses_outputs   = ["seepage_network"]
   normalize_cost = true

   [[calibration.objective_blocks]]
   name         = "hydrograph"
   metric       = "nse_log"
   uses_outputs = ["gauged_discharge"]

   [[calibration.phases]]
   name             = "transient_storage"
   max_iter         = 30
   tolerance        = 0.05
   parameters       = ["Sy"]
   objective_blocks = { hydrograph = 0.8, network_extension = 0.2 }
   depends_on       = "steady_conductivity"
   regime           = "transient"

   [calibration.phases.scoring_window]
   start = "2001-01-01"

Five things in there are not free choices.

``support = "point"`` with ``observes``, for the gauge
   The single-metric route declares no output, so a stage that scores two
   criteria has to name the gauge as one. That form reads what the
   single-metric route reads, which is what keeps the two costs comparable:
   the station's own cell where the loader placed one, with the runoff of
   ``[data.runoff]`` added over the area that cell drains, and the
   whole-catchment series where it placed none, with the basin's runoff added.
   A discharge station is deliberately never placed by the coordinates written
   beside it, so the second case is the ordinary one, and the run logs one line
   naming the station when it takes it. ``hmp calibrate --list-phases`` prints
   it as ``discharge, station NANCON (whole-catchment series)``. An ``x``, ``y``
   or ``geometry`` written beside ``observes`` is not read, and loading warns
   so, unless ``snap_radius`` is set. The same target written
   ``support = "boundary"`` on the drain
   validates and scores the drain budget instead, which is baseflow without
   runoff and not what a gauge records.

   ``snap_radius`` is the opt-in exception, on a ``support = "point"`` or
   ``support = "cell"`` discharge output. A gauge coordinate rarely sits on
   the talweg the model routes on: on the Nancon it resolves to a cell
   draining 0.107 km2 of the 64.6 km2 catchment. With a radius, the output
   is moved onto the cell that drains the most within that distance before
   it is scored, and a station named in ``observes`` is then placed by the
   coordinate of its record and snapped from there.

   .. code-block:: toml

      [calibration.outputs.gauged_discharge]
      support     = "point"
      variable    = "discharge"
      observes    = "NANCON"
      x           = 389285.910
      y           = 6816518.749
      snap_radius = "150 m"

   The drained area searched is the one the solver accumulates on the mesh,
   on the graph the discharge is routed on, ``diagonal_neighbors`` included.
   The delineation's own outlet snap works on the DEM raster instead, and its
   snapped outlet resolves to a mesh cell draining 0.022 km2, so that surface
   is not reused. The radius is a maximum displacement from the gauge, not the
   window width ``geographic.snap_dist`` is. Each trial logs the distance
   moved and the area drained before and after. A radius that reaches no cell
   but the one the gauge already sits in is refused, with the distance to the
   nearest other cell, and two outputs snapped onto one cell are named in a
   warning, since they would score one series against two records. Without
   ``snap_radius`` nothing moves, which keeps every existing project where it
   was.

``scoring_window``, for the spin-up of both blocks
   ``start = "2001-01-01"`` is the first date scored, and 2000 is simulated
   and not scored. A series keeps its stamps inside the window. The network
   output reads one state, dated at the stamp that closes the period it
   reads: the last month here, stamped 2003-01-01, inside the window. A
   window that does not hold that stamp is refused, naming both, by
   ``hmp calibrate --check`` and at the first trial, rather than scored under
   the name of a windowed cost. ``warmup`` and ``warmup_periods`` still load
   but count samples, twelve being a year at a monthly step and twelve days
   at a daily one; the window names the same span at any step.

The network block, in transient, scores one instant
   A network output reads exactly one state unless it declares an ``extent``
   table: ``time = "last"`` (default), ``"first"``, or an ISO date such as
   ``"2002-10-15"``, which reads the state of the period that holds it,
   ``[start, end)``. The extraction serves the criterion that row and no
   other. On a steady phase the one period spans the whole record, so every
   date of it reads its one state and the same output serves both stages.
   ``"all"`` and a list of dates are refused at configuration load. A
   transient comparison against the two mapped extents, counted over the
   calendar years of the run, is the two-bound mode of
   `Two maps and two bounds`_ below: it reads the maps already declared on
   this output and needs no observed intermittence record. Scoring against an
   actual seasonal intermittence record instead is the method of
   :cite:`abherve2024headwater`, a different observation altogether.

``normalize_cost`` on the network block, then a share table
   The two costs are in different units: ``distance_gap`` is metres and
   ``1 - nse_log`` is a pure number. ``normalize_cost = true`` on the network
   block divides each distance by the output's ``validity_length`` (Eq. 4,
   ``"auto"`` = 2 h_obs, 150 m on the Nancon mesh), so the gap is counted in
   validity lengths and a gap of one costs as much as an NSE of zero. It stays
   refused on ``nse_log``, already dimensionless. A table,
   ``{ block = share, ... }``, then gives the phase its own balance between two
   pure numbers instead of a weight declared once on the block itself, which
   would also apply to any other phase that reads it. Shares are normalized to
   sum to one, so the trial cost above is
   ``0.2 * |gap| / L + 0.8 * (1 - NSElog)``. Read ``network_extension.total``
   and ``hydrograph.total``, which every trial reports, to see what it bought.
   Without ``normalize_cost`` the table is an exchange rate between metres and
   an efficiency, and ``{ hydrograph = 100, network_extension = 1 }`` was the
   spelling it needed.

``regime = "transient"`` in place of an override
   The first stage writes ``regime = "steady"``, and this one restates
   ``regime = "transient"``, which is what "then" means between the two: a
   phase without ``regime`` runs the project's own time grid, but this stage
   comes right after one that changed it. Writing ``regime`` instead of
   ``[calibration.phases.overrides] "flow.flow_regime" = "transient"`` is the
   same override, produced for the phase instead of typed into it.

No ``method`` on this stage
   The hydrograph block is not signed, so the phase has a cost to minimise and
   is handed ``scipy_nelder_mead`` on its own; ``--list-phases`` prints the
   choice and why. Write ``method`` only to run something else, such as
   ``"cma_es"`` for a global search.

Two maps and two bounds
-----------------------

Everything above scores one mapped network. A ``support = "network"`` output
can carry two, and a transient run can then be scored on a definition of
"flowing" that holds over a year rather than at one instant. Nothing here
touches ``matching_hydrographic_network``: the protocol still writes the
paper's two stages exactly as before, and this is an option of the network
*output*, usable in any phase, hand-written or protocol-expanded.

The maximal map is every mapped reach declared by ``observed_network`` or
``stream_geometry_path`` — the existing source, and, alone, the default and
usually the only map a project carries. A minimal map, the *permanent*
reaches, may be declared beside it:

.. code-block:: toml

   [calibration.outputs.seepage_network]
   support                      = "network"
   stream_geometry_path         = "complete_network.gpkg"
   minimal_stream_geometry_path = "permanent_network.gpkg"

``minimal_observed_network = "data.hydrography"`` reads the permanent
reaches the hydrography data family wrote beside its own network instead of
naming a second file — it can only do that when the source says which
reaches are permanent, BD Topage among them. Declare one route or the other
for the minimal map, never both, and read it as it is: no attribute filter
runs in calibration, so a source that mixes permanence classes in one file is
not something a calibration output can split on its own.

The maximal map scored is the **union** of the two files: wherever the
minimal map disagrees with the maximal one, the wider of the two is scored,
never a network the criterion had to fix. ``frac_minimal_outside_maximal``
publishes how much they disagreed, as the share of the minimal map's cells
of the scored catchment the maximal map missed before the union. On two
files digitised independently that share is rarely zero, and it is a
property of the maps, not of the model — read it once per pair of files, not
per trial.

Steady state, the papers' case
   Without a minimal map, the one scored state is compared to the maximal
   map, exactly as every earlier section of this page describes. **With
   both maps declared, the state is compared to the minimal (permanent) map
   instead** — the practice of :cite:`abherve2025climate` — and the maximal
   map is scored at the same state as a **validation**, published under the
   suffix ``_maximal_validation`` and never entering the cost. A search
   pointed at ``J_signed_maximal`` would therefore find nothing: that key
   does not exist when only one state is scored, by design, so a root
   search cannot silently close on the validation map instead of the map
   that drove it.

Transient, the two-bound mode
   Declaring an ``extent`` table switches the output from one state to every
   complete calendar year of a transient run:

   .. code-block:: toml

      [calibration.outputs.seepage_network.extent]
      maximal_flowing_steps = 1
      minimal_dry_steps     = 1
      year_quorum           = 0.5
      visible_flow          = "1 L/s"

      [calibration.outputs.seepage_network.extent.weights]
      minimal = 0.5
      maximal = 0.5

   For every complete calendar year — a timestep belongs to the year its
   *midpoint* falls in, and a year the run does not cover whole is dropped —
   two masks are built from the count of timesteps each cell flowed that
   year. A phase ``scoring_window`` keeps only the complete years it holds,
   which is how the spin-up year leaves the score. A hand-written phase says
   it; the transient stage of ``matching_hydrographic_network`` writes one by
   default, from one year after the run's start, so a network block scored
   there leaves its first year out like the hydrograph does:

   - the **maximal** simulated mask holds the cells flowing at least
     ``maximal_flowing_steps`` timesteps of the year;
   - the **minimal** simulated mask holds the cells flowing at every
     timestep of the year but at most ``minimal_dry_steps``.

   **Both count TIMESTEPS, never days**: a weekly or a monthly run would
   otherwise see its rule silently tighten or loosen with the step length. A
   year of 12 monthly steps and ``maximal_flowing_steps = 1`` asks a cell to
   flow one month out of twelve; the same default on a daily run asks one day
   out of 365. Declaring ``minimal_dry_steps`` looser than
   ``maximal_flowing_steps`` is refused before the first trial, because it
   would make the permanent mask wider than the complete one, an answer that
   contradicts what "permanent" and "complete" mean.

   Across years, a cell enters the **climatological** mask scored — the one
   compared to the map — when it meets its year's rule in at least
   ``ceil(year_quorum * n_years)`` of the scored years, ``year_quorum``
   defaulting to one half. Fewer than three scored years logs a warning: with
   two years, a quorum of one half is their union, which reads less like an
   ordinary "most years" than it sounds.

   The output is refused, before the first trial, on a single steady period,
   on a run covering no complete calendar year, or on a step rule the
   shortest complete year cannot hold (``maximal_flowing_steps`` above its
   timestep count, or ``minimal_dry_steps`` too generous for it).

   Each bound is then scored **once** by the same distance criterion as the
   steady mode (``seepage_distance_cost``): the maximal mask against the
   maximal map, and, when a minimal map is declared, the minimal mask against
   the minimal map. With one map only, the maximal bound alone is scored.
   Each scored year is also scored the same way as a diagnostic, published as
   ``J_signed_<bound>_y<year>`` and ``n_network_sim_<bound>_y<year>``, so a
   trend across the record is visible without a second search.

"Flowing", one definition for the criterion and the figures
   A cell flows at a timestep when it lies in the downstream closure of the
   *seepage* cells — release above :math:`\tau \cdot R \cdot A`, exactly the
   steady mode's threshold — on the criterion graph, and, unless
   ``visible_flow`` is ``"0 L/s"``, when its **routed discharge** also
   reaches ``visible_flow``. The routed discharge is the release of the
   seepage cells accumulated down the same graph: a seepage flux, never a
   river discharge, so it carries no runoff and no bed loss. It never
   decreases downstream, so the flowing mask stays closed downstream
   whatever the threshold.

   ``visible_flow`` applies only to this transient mode; the steady, one-state
   paper mode above stays purely geometric (the closure alone), because that
   is the criterion :cite:`abherve2023` published and measured biases
   against. Write it as a discharge with its unit, ``"1 L/s"`` or
   ``"0.002 m3/s"``, or as a share of the outlet's own routed discharge at the
   same timestep, ``"1%"``; a bare number is refused, because a metre-cube
   reader and a litre reader would silently disagree. **It is never scaled
   with the cell size**: a cell's area is a numerical choice, the discharge a
   field observer would see flowing is not.

   No value is agreed in the literature. The closest precedent thresholds a
   *simulated* discharge at 10 L/s, a small share of the two virtual
   catchments' own outlet flow, to map their active network
   (:cite:`zanetti2024nonperennial`); field zero-flow gauge thresholds of
   about 1 to 3 L/s are in use to absorb measurement noise at low flow
   (:cite:`zimmer2020zeroflow`). ``"1 L/s"``, the default, sits at the low end
   of both. ``"0 L/s"`` recovers the geometric definition exactly, with no
   discharge test at all.

Combining two bounds into one value
   Each bound has its own root, :math:`K^*_{minimal}` and
   :math:`K^*_{maximal}`, found by one bisection sweep that brackets both
   residuals — ``J_signed_minimal`` and ``J_signed_maximal`` — on the same
   trials. The value a two-bound search returns is their **weighted geometric
   mean**,

   .. math::

      \log K = w_{minimal} \log K^*_{minimal} + w_{maximal} \log K^*_{maximal}

   with the weights of ``[calibration.outputs.<name>.extent.weights]``,
   0.5 / 0.5 by default and required to sum to one. That value is then
   **evaluated once more**, as an ordinary trial, so every number published
   beside it — components, Equation 4, the figures — comes from a real solve
   and not from an interpolation between two others. The report's
   ``extra.roots`` carries both roots (their trial, residual, weight and
   final bracket), ``delta_log10 = log10(K*_maximal / K*_minimal)`` and the
   combined trial id; there is no ``extra.bracket`` and no
   ``parameter_intervals`` in this mode, because the interval around one
   value has no meaning between two roots — read ``delta_log10`` as the
   spread instead. The budget is known before the first solve too: 24
   evaluations inside the declared bounds on the Nancon's search interval and
   sweep, 26 to 32 after one to four bracket expansions, against 15 to 23 for
   a one-bound search on the same interval.

   A minimising engine (Nelder-Mead, CMA-ES, ...) has no root to combine, and
   minimises

   .. math::

      \mathrm{cost} = w_{minimal} \lvert J_{minimal} \rvert
                    + w_{maximal} \lvert J_{maximal} \rvert

   instead — the criterion's ``distance_gap`` summed over both weighted
   pairs. **Caveat**: a weighted sum of two V-shaped costs tends to settle at
   one of the two roots rather than at a point between them, since moving off
   either root only ever increases one term. A bisection is the estimator
   this mode was designed for; a minimiser answers a related but different
   question.

   A bound weighted zero is not searched at all: weights ``{minimal = 1,
   maximal = 0}`` reduce a two-root search to one root on the minimal bound,
   with no wasted solve, the practice of :cite:`abherve2025climate` read
   literally. Weights other than 0.5 / 0.5 without a minimal map are refused
   at load: they would weigh a bound that is never scored.

Reading the component keys
   ``n_bounds_scored`` (1.0 or 2.0) says how many bounds are in the cost, and
   it is what the search and the reader both key on.

   - **One bound** (no ``extent``, or ``extent`` with one map): the full set
     of components this page already documents, unsuffixed — ``J_signed``,
     ``D_so``, ``D_os``, ``Doptim``, ``roptim``, ... — plus the same set again
     suffixed ``_maximal`` (one map) or ``_minimal`` (one state, both maps).
   - **Two bounds** (``extent`` and a minimal map, both weights above zero):
     **only** the suffixed sets exist — ``J_signed_minimal``,
     ``J_signed_maximal``, ``roptim_minimal``, ``roptim_maximal``, and so on
     — plus ``weight_minimal`` and ``weight_maximal``. There is no unsuffixed
     ``J_signed`` to read by accident: a single-root bisection pointed at
     this output finds nothing, rather than silently closing on whichever
     bound happens to come first.
   - **One state with both maps**: the minimal bound's set is the cost, both
     unsuffixed and again as ``_minimal``; the maximal map's set is published
     as ``_maximal_validation`` and never as ``_maximal``.
   - The extent mode adds ``J_signed_<bound>_y<year>`` and
     ``n_network_sim_<bound>_y<year>`` per scored year and bound, plus
     ``n_years_scored``, ``n_years_required``, ``first_year_scored``,
     ``last_year_scored``, ``n_steps_min_per_year``, ``year_quorum``,
     ``maximal_flowing_steps``, ``minimal_dry_steps``, ``visible_flow_m3_s``
     and ``visible_flow_outlet_share``.
   - Any minimal map, in either mode, adds ``frac_minimal_outside_maximal``.

   ``roptim_verdict`` follows the same split: a two-bound output publishes
   ``roptim_verdict.<output>_minimal`` and ``roptim_verdict.<output>_maximal``
   instead of one unsuffixed entry, each read at the trial the search
   returns and each carrying its own ``snap`` verdict when
   ``[geographic.snap_streams] mode = "apply"``.

Deviations to declare
   A run using the extent table departs from the papers in five ways that
   belong in a methods paragraph beside the calibrated value: it scores
   transient masks over calendar years rather than one steady state; the
   duration rule is counted in timesteps, not days; a climatological quorum
   decides which cells count across years; a visible-flow threshold, not only
   the geometric closure, decides what "flowing" means; and, with two maps,
   the two bounds are combined with declared weights. The
   ``matching_hydrographic_network`` protocol itself is unchanged by any of
   this: it still writes the paper's two steady/transient stages, and the
   extent table is something a hand-written phase, or a protocol-expanded one
   edited afterwards, opts into on its network output. The ``scoring_window``
   its transient stage prints under ``hmp calibrate --expand``, one year after
   the run's start unless the file declares one, is the phase's: it bounds a
   two-bound network block pasted into that stage as well, and is refused
   beside a network block in one state, which has no year to cut.

A figure outside any calibration
   ``network_extent_bounds_map`` draws the maximal and minimal simulated
   extents of a transient run against the two stored maps without running any
   search: point ``[display].figures`` at it on a run that stored both
   ``reference`` (the complete network) and ``reference_permanent`` (the
   permanent one). See :doc:`/user_guide/figures` for its options; it reports
   cell counts only, no distance.

Measured on the Nancon
----------------------

The calibration files of example 04 were run on 2026-09-28, same code and same
machine. Every stage two scores from 2001-01-01, 2000 being spin-up, and a
monthly stamp closes its month, so the gauge is compared with the month the
stamp ends (commit ``e6c5e50f5``). A score taken before that fix is not
comparable with these.

.. list-table::
   :header-rows: 1
   :widths: 16 28 28 28

   * -
     - ``run_calibration.toml``, the protocol
     - ``run_calibration_by_hand.toml``
     - ``run_calibration_bdtopage.toml``
   * - stage one
     - ``K`` = 8.107e-05 m/s, signed gap -1.96 m, 15 trials
     - identical, to the trial
     - two roots, ``K*`` = 2.564e-05 on the permanent map and 1.358e-06 on
       the complete one, combined 5.9e-06, 24 trials
   * - stage two
     - ``Sy`` = 0.045, NSElog 0.916, 8 trials
     - identical, to the trial
     - ``Sy`` = 0.056, NSElog 0.922, 6 trials

The file written by hand reproduces the protocol to the trial, which is what it
is for: the recipe written out as two phases, each key visible.

The gauge does not tell the conductivities apart. From 5.9e-06 to 8.1e-05, a
factor of fourteen, the stage two fit stays between 0.914 and 0.922 of NSElog,
and the whole simplex of the protocol moves it from 0.9154 to 0.9160. At a
monthly step the hydrograph follows the recharge it is given: it reads ``Sy``,
within about ten per cent, and leaves ``K`` to the network. Its volume is short
by 20 to 21 per cent at every calibrated point, because the recharge and
runoff files of the example carry 79 per cent of the gauged volume over
2000-2002, which no parameter changes.

The two BD Topage roots are 1.28 decades apart, so no homogeneous ``K`` holds
both maps. Inside the catchment the simulated extent grows by a factor of about
1.4 from its yearly minimum to its maximum, the maps by a factor of 2.83. The
combined value holds neither bound, and the permanent one fails Eq. 4 at it
(``Doptim`` = 209.8 m against 150 m).

The validity indicator clears its bound at the protocol's ``K``. ``roptim`` is
the agreement between the two networks in cells of ``h_obs``; example 04
declares neither an accuracy nor a snap, so its validity length is two cells,
150 m, and it is valid at 2 and under. It runs from 1.43 to 10.3 over the stage
one sweep and is 1.51 at the retained ``K`` (``Doptim`` = 113.3 m).
``alpha_obs_closure_catchment`` is 0.78 against 0.90: the mapped network agrees
poorly with the model top, so the distances carry that disagreement on top of
the hydrogeology. A ``K`` read off this example is a demonstration, not a number
to cite, and the ratio ``K/R`` is what to publish, here with ``R`` =
9.075e-09 m/s.

What each choice buys you
-------------------------

``method = "bisection"``
   A root search, not a minimiser. The criterion has a zero, not a minimum, and
   the two are not the same point. It stops on the width of the bracket, never
   on the size of the residual: the residual is a step function that jumps over
   zero and may never get small. It searches one parameter, and that parameter
   has to declare ``transform = "log"``: the width it stops on is a width in
   that variable, so on any other transform it would read as an absolute one.
   A two-parameter space and a non-log transform are both refused.

``sweep_points = 7``
   A coarse logarithmic sweep before the bisection. It checks the monotonicity
   the paper assumes rather than supposing it, it sees every crossing, and the
   crossing curves come out of the same solves. Set it to zero for the pure
   bisection of the paper.

``max_iter`` of the bisection
   Its budget is known before the first solve, so the default ``"auto"`` lets
   the search count it. With ``d`` the declared interval in decades,
   ``t = log10(1 + rel_tol)``, ``S`` sweep points (two when ``sweep_points`` is
   zero), ``s = d / (S - 1)`` the sweep step and ``E = bracket_expand``:

   - a root inside the bounds costs ``S + ceil(log2(s / t))``, the nominal count;
   - a root found after ``e`` expansions costs ``S + 2e + ceil(log2(1 / t))``,
     since each expansion evaluates two new ends and leaves a bracket one
     decade wide;
   - ``"auto"`` budgets the largest of these, the worst case.

   On the Nancon, ``[1e-7, 1e-3]`` m/s, seven sweep points and one per cent:
   15 inside the bounds, then 17, 19, 21 and 23 after one to four expansions,
   so ``"auto"`` is 23. The ``20`` the protocol used as its default covered two
   expansions; the ``18`` written above covers one, and
   ``hmp calibrate --check`` says so. A number below the nominal count is
   refused, by ``--check`` and again before the first solve, with the count to
   write. If the budget still runs out, for instance on failed trials, the
   search is granted exactly the halvings its bracket still needs, once, with
   a warning, and only if they fit in half the budget.

   Nelder-Mead, stage two by default, cannot count what it needs and gets no
   extension. Spending ``max_iter`` before its tolerance leaves the stage not
   converged: the report says so, the session closes as ``partial``, nothing
   is frozen and a stage that depends on it is refused. Run it again with a
   larger ``max_iter``: the trials already solved come back from the cache.

``[calibration.phases.overrides]``
   The two stages do not run the same model: the first is steady and reads a
   seepage mask at equilibrium, the second is transient over a span long enough
   to shape the recessions. The flow regime and the simulated period are
   properties of the model rather than of the search, so the phase declares
   them. A phase is refused if it overrides a path another phase freezes, or if
   it rewrites the calibration section under itself.

``points_per_dim`` on a grid phase
   What sets the number of points, not ``max_iter``. The grid adapter defaults
   to five per dimension and ``max_iter`` is only a ceiling, so a phase asking
   for nine trials without this keyword runs five.

``weighting = "area"``
   Recommended as soon as the mesh is refined along the streams, which is the
   usual refinement: an unweighted mean over-samples the river corridor, where
   distances are smallest. Both weightings are always reported, and their gap
   measures that effect directly.

``tau_specific_ratio``
   A cell releasing less than this fraction of its own recharge is not a
   stream. Zero reproduces the criterion of the paper, which gives no threshold
   at all.

   **Leave it at its default, and do not read it as a working knob.** It is
   inert as defined: a cell that releases at all carries the drainage it
   collects from everything upslope, a hundred to a thousand times its own
   recharge, so a fraction of that recharge never excludes anything. Measured on
   the Nancon at the calibrated conductivity, over the 380 cells releasing
   inside the catchment, not one had a flux below the threshold, and raising
   the ratio to 100 still kept 28.

   Thresholding the total release instead was tried and is worse: at
   ``1e-4`` of ``R * A`` the cut lands at 4.9e-4 m3/s, above the many small
   releases a low conductivity spreads over the catchment and below the few
   large ones a high conductivity concentrates. The simulated network then
   GROWS with the conductivity instead of retracting, the residual loses its
   monotonicity, and the root moves three decades. What the threshold should be
   a fraction of is an open question; neither answer tried so far is right.

``observed_rasterization``
   How the mapped network becomes cells. ``"crossing"``, the default, keeps the
   cell holding each point where a line crosses the segment joining two
   edge-sharing cell centres: on a structured grid it is WhiteboxTools
   ``VectorLinesToRaster``, the paper's tool, and it draws the map one cell
   wide like the simulated network, so a model that reproduces the map scores
   zero. ``"touch"`` keeps every cell the line touches, corners included, and
   replays a session made before 2026-09. On the Nancon at 75 m it draws 730
   cells against 490, and the root moves by about ten per cent. Each trial
   records ``n_observed_cells`` and ``n_observed_features_fallback``, the
   reaches that crossed no segment and were kept at their midpoint cell. The
   figures redrawn from a run use the same rule and default.

``objective = "nse_log"`` in the second stage
   The Nash-Sutcliffe efficiency on log-transformed series, which weights the
   recessions. Do not write ``transform = "log"`` for this: that takes the
   logarithm of an already-computed cost and is an unrelated operation.

``variable`` and ``objective`` on the second stage only
   Declaring either one picks the single-metric route for that phase. The
   phase then inherits neither the outputs nor the objective blocks the
   calibration declares, which is what keeps the transient stage off the
   network criterion of the first one. Declaring both conventions on the same
   phase is refused rather than silently resolved.

``scoring_window`` rather than ``warmup_periods``
   A window in dates means the same span whatever the output frequency; a count
   of samples does not. The two are mutually exclusive and declaring both is
   refused.

Running it
----------

.. code-block:: console

   $ hmp calibrate calibration.toml
   $ hmp calibrate calibration.toml --list-phases
   $ hmp calibrate calibration.toml --phase steady_conductivity

The first form is the one to use. It runs the phases in declaration order and
is the only form that produces the two-stage result the page describes.

``--list-phases`` prints the declared phases and exits without running
anything.

``--phase`` selects a single phase, and it only accepts one that does not
depend on another. On the configuration above that means ``steady_conductivity``,
and nothing else: ``--phase transient_storage`` is refused, because
``transient_storage`` declares ``depends_on = "steady_conductivity"`` and a phase whose
dependency did not run in the same invocation is missing the values that
dependency freezes. The runner refuses rather than running it against the
baseline the TOML declares, which would be a different calibration with nothing
in the result to say so. There is no way to hand a frozen value in from a
previous invocation: to run the second stage, run both.

Reading the output
------------------

Every trial writes close to forty diagnostics into ``trials.jsonl`` and into the
iteration table. They are all prefixed with the name of the output that
produced them, so the keys below read ``seepage_network.J_signed``,
``seepage_network.roptim`` and so on in the files. They are written whether or
not a run is promoted; the configuration above promotes one, the best. The ones
to look at first:

``n_bounds_scored``
   1.0 for everything on this page above "Two maps and two bounds", 2.0 for an
   output scoring the transient extent table against both a maximal and a
   minimal map. It decides which of ``J_signed`` or ``J_signed_minimal`` /
   ``J_signed_maximal`` exists on a trial; see that section's "Reading the
   component keys" for the full split.

``J_signed``
   The signed residual. Its sign says which side of the balance the trial is
   on, and it is what the search brackets. If it never changes sign over the
   sweep, the search widens the interval by a decade on each side, up to
   ``bracket_expand`` times (four by default), then raises and names both ends
   rather than returning the better of the two. One failed evaluation anywhere
   in the sweep skips the widening: the surface is the problem, not the
   interval. A root that only exists outside the declared bounds is returned
   with a warning naming both, because several decades out is usually a
   residual that stopped responding to the parameter rather than a surprising
   value.

``roptim``, ``roptim_valid``, ``validity_length_m``
   ``roptim`` is ``Doptim / h_obs``, the paper's Equation 3, kept to compare
   with its Table 1. ``roptim_valid`` is Equation 4, ``Doptim <=
   validity_length_m``, and ``validity_length_provenance`` says what set the
   length ("The validity length" above). All three are recorded on every
   trial. The bound **qualifies** the result and does not withhold it: a
   violation warns and the value comes back, unless you set
   ``on_roptim_violation = "error"``, which raises instead. And it measures
   agreement, not correctness, so do not read it as a quality score of the
   model.

``roptim_verdict``
   The bound of Equation 4, read once, on the trial the search returns, the
   way the paper reads it: "At this point" (HESS p. 3225), not on the way
   there. A report entry per network output, ``{value, Doptim, h_obs_m,
   validity_length_m, provenance, valid, causes}``: ``value`` is ``roptim``,
   ``provenance`` the name of what set the length, and ``causes`` lists what
   failed, ``doptim``, ``snap`` or ``empty``. A ``Doptim`` that is not a
   number, an empty simulated network at the returned trial, counts as a
   violation. With ``on_roptim_violation = "error"`` the raise happens after
   the session is saved, so every trial is still on disk, and a staged
   calibration stops there rather than freezing an unqualified value into a
   dependent phase. An output scoring two bounds (``n_bounds_scored`` = 2, see
   "Two maps and two bounds") has no unsuffixed entry: it publishes
   ``roptim_verdict.<output>_minimal`` and ``roptim_verdict.<output>_maximal``
   instead, each read on the same returned trial against its own length.
   ``h_obs_m`` in every entry is ``h_obs``, not the mesh's median cell size
   ("Snapping the mapped network" above): the cell size where the mapped
   network itself lies. With ``[geographic.snap_streams] mode = "apply"``,
   ``valid`` also requires the displacement and rejected-share bounds, and
   the entry then carries a ``snap`` sub-record; see the same section.

``R_mean_m_s``
   The denominator of the calibrated ratio. It is what makes the result a
   ``K/R`` rather than a ``K``, and comparing it across the trials of a session
   is how you check the first stage really held the recharge still.

``d_sat_m``, ``d_aquifer_m`` and ``d_sat_over_d``
   The paper's ``dsat``: the saturated thickness the model computes, averaged
   by area over the catchment at the state the network is read from, then the
   imposed thickness over the same cells and their ratio. A backend that
   serves no saturated thickness publishes none of these and still scores the
   network.

``d_sat_dry_fraction``, ``d_sat_inactive_fraction`` or ``d_sat_unset_fraction``
   The share of catchment area left out of ``d_sat_m`` because its thickness
   is not finite. MODFLOW writes one sentinel for a dry cell (HDRY) and
   another for a cell it never solved (HNOFLO), and the thickness alone
   cannot tell them apart. When the mesh carries an inactive mask (IDOMAIN,
   lake footprints included) the share splits: ``d_sat_dry_fraction`` is an
   active cell with no water table, a physical state that biases ``d_sat_m``
   upward, and ``d_sat_inactive_fraction`` is outside the solved domain, a
   modelling choice rather than a state. A mesh without that mask publishes
   the single ``d_sat_unset_fraction`` instead.

``alpha_obs_closure`` and ``frac_reachable_obs_raw``
   How much of the criterion's own measurement is a top-versus-map
   disagreement, and how much of the scored catchment has a descent that
   reaches the mapped network without the sealed outlet. ``alpha_obs_closure``
   is measured on the model top and
   not on the burned routing DEM, so a low value is not evidence the burning
   was skipped: read it beside the ``alpha`` of the geographic step, as the
   second item of "Before you start" says. They describe the geometry, not the
   trial, so they are identical across a session: the static geometry is
   rebuilt at every trial from the same topography and comes out the same.

``alpha_obs_closure_catchment`` and ``frac_obs_outside_catchment``
   The same ratio on the support the criterion actually scores, and the share
   of the mapped cells that sit outside the scored catchment. Outside the
   catchment the mesh is a buffer: nothing there is required to descend into
   the network, so a linework wider than the catchment inflates the closure of
   ``alpha_obs_closure`` without adding to its numerator. On the Nancon 55 per
   cent of the mapped cells are out, and the two ratios read 0.306 and 0.693
   while one outlet sealed the whole mesh.
   **Read the catchment one to judge the agreement**, and the whole-mesh one
   only to see how much linework the criterion carries beyond the basin. A run
   whose ``reference`` network is already clipped, which is what the data
   pipeline persists, has the two agree.

``catchment_mismatch``
   The catchment the criterion scores is read on its own graph: every cell
   whose descent on the model top, flooded from the domain border, reaches the
   outlet. The outlet is the most accumulated cell within two cells of the
   pour point the geographic step snapped. The raster polygon of the
   delineation only builds the domain and places that outlet, and this number
   is the area of their symmetric difference over the area of the polygon. A
   value above 0.05 is logged as a warning: an outlet on another branch, or a
   mesh much coarser than the DEM. On the Nancon grid at 75 m it reads 0.002.

``frac_unreachable_so`` and ``frac_unreachable_os``
   The share of each support whose descent ends without meeting its target.
   The bound holds on ``frac_unreachable_so`` alone: its target is the mapped
   network with the outlet sealed in, which does not move between trials, so
   beyond ``max_unreachable_fraction`` (five per cent by default) the trial
   fails loudly, because averaging over a truncated support is a fiction and
   the cells dropped are never a random sample: they sit upstream of a pit.
   ``frac_unreachable_os`` is reported and deliberately unbounded. Its target
   is the SIMULATED network, which the calibration moves: at a high
   conductivity the simulated streams retract into the talwegs and mapped cells
   legitimately have nothing left to descend into. Those cells saturate at
   ``L_cap``, and the value is the signal the search reads at the high end of
   its bracket, not a broken surface.

``D_so_median``, ``D_so_p90``, ``D_so_top5_share``
   The shape of the tail, with ``D_os_median``, ``D_os_p90`` and
   ``D_os_top5_share`` beside them for the other support. The median is usually
   zero and a few long branches carry most of the value, so the mean is not a
   typical gap.

``n_valid``, ``n_excess``, ``n_missing``
   The three-class counts. The criterion balances the last two against each
   other, which is what the confusion map draws.

``D_so_over_D_os``, the four ``overlap_*`` indices, ``n_neither``, ``L_sim_m``, ``L_obs_m``
   Secondary diagnostics, never scored, that follow the ``fuzzy`` and
   ``total_length`` outputs of the authors' own published code (Zenodo
   8311547). ``D_so_over_D_os`` is the ratio it branches its dichotomy on;
   its crossing of one is the zero of ``J_signed``, so it adds a scale-free
   reading and no new information. ``n_neither`` counts a cell neither
   simulated nor mapped, ``overlap_Ea`` reads the agreement between the two
   network sizes, ``overlap_Sa`` the excess relative to the mapped size,
   ``overlap_Na`` the missing share relative to what the map leaves without a
   stream, and ``overlap_E`` their product. ``L_sim_m`` and ``L_obs_m`` are
   each network's length, the sum of ``sqrt(cell area)`` over its cells.
   Three departures from that published code: the counts use the criterion's
   own supports, the catchment without water bodies, where the published code
   counts every basin pixel; the mapped side is the raw network, as ``D_os``
   reads it, where the published code counts it closed downslope; and a
   length sums cell sizes rather than the WhiteboxTools polylines the
   published code vectorises, so it drops no stub and never applies the
   published two-cell, 110 m filter.

What it looks like on a real catchment
--------------------------------------

``examples/projects/21_nancon_network_calibration`` runs the configuration
above on the Nancon at Fougeres, 64.64 km2 in Brittany, in two variants: a
Cauchy drain over the whole surface (``auto_drn_full.toml``) and the main
reaches routed in SFR (``auto_sfr_drn.toml``). Its ``README.md`` carries the
measured numbers and their date, and is the one to read for the current
figure: the SFR bed elevation was corrected on 2026-09-06, every session
committed before that date calibrated the wrong geometry, and the README
says so rather than letting a stale number stand unlabelled. At last
measurement ``roptim`` ran from 3.93 to 12.01 over the sweep, above its bound
of two, so every trial is returned qualified rather than withheld; the two
known departures the README also carries are a one-layer model against the
paper's six, and a mapped drainage density 2.1 times looser than Table 1
because the linework is filtered to the perennial network. A stage two
pinning ``Sy`` on a search bound is what a stage that identifies
:math:`S_y/T` does when it is handed a biased :math:`T`: it saturates instead
of absorbing, rather than a sign that the search failed.

Two things that example shows and this page cannot: the same catchment
calibrated under both MODFLOW backends, eleven per cent apart on the root; and
the same catchment again with the reaches in SFR, which is what puts the
release union of the previous section under load.

The figures
-----------

Ten figures are registered for this method: ``downslope_distance_crossing``,
``bisection_bracket_trace``, ``parameter_cost_profile``,
``matching_hydrographic_network_card``, ``seepage_network_reference_overlay``,
``seepage_network_confusion_map``, ``downslope_distance_map``,
``hydrograph_log_nse``, ``observed_network_snap_map`` and
``observed_network_snap_histogram``. ``network_extent_bounds_map``, the two
simulated extents against the two maps ("Two maps and two bounds" above), is a
related figure that reads a run directly and needs no calibration session at
all.

All ten are declared, never scripted. List them in ``[display].figures`` of
the project or of the calibration TOML and the promoted run renders them like
any other figure of the gallery:

.. code-block:: toml

   [display]
   figures = [
       "downslope_distance_crossing",
       "bisection_bracket_trace",
       "parameter_cost_profile",
       "seepage_network_reference_overlay",
       "seepage_network_confusion_map",
       "downslope_distance_map",
       "hydrograph_log_nse",
       "matching_hydrographic_network_card",
       "observed_network_snap_map",
       "observed_network_snap_histogram",
   ]

The first four read the trials of the session straight off the run. The three
network maps rebuild the per-cell partition the criterion scored, through the
same construction it used
(:mod:`hydromodpy.core.stream_geometry`, reached from
:func:`hydromodpy.results.derive.stream_network.network_comparison_from_run`),
so a map cannot disagree with the ``n_valid``, ``n_excess`` and ``n_missing``
the trial published. They need three things from the run and say which one is
missing when it is: a per-cell ``release_flux``, a ``reference`` hydrographic
network, and a delineated watershed. The first comes from
``[simulation.results.derived] release_flux = true``, the second from
``[[data.hydrography.sources]]``.

Their knobs go through ``[display.overrides]``, so a reader can move the
threshold the partition depends on, or read the other direction of the
distance, without touching code:

.. code-block:: toml

   [display.overrides.seepage_network_confusion_map]
   tau_specific_ratio = 0.0

   [display.overrides.downslope_distance_map]
   direction = "to_simulated"

The three maps open on the delineated catchment, because that is where every
class of the criterion lives: on the Nancon the partition holds 1 681 cells
out of a mesh of 60 395, and a frame drawn around the mesh spends its page on
ground that carries no answer. A reader checking what the model does outside
the basin it was scored on asks for the whole domain instead:

.. code-block:: toml

   [display.overrides.seepage_network_reference_overlay]
   extent = "mesh"

An eleventh figure, ``roptim_validity_chart``, compares the calibrated
agreement of SEVERAL catchments, and a run holds one. It refuses a run-driven
render by name rather than drawing one point, and it is fed per-site records
directly.

The two snap figures, ``observed_network_snap_map`` and
``observed_network_snap_histogram``, are described under "Snapping the mapped
network" above; both refuse by name on a run whose
``[geographic.snap_streams]`` is ``off``.

``matching_hydrographic_network_card`` is a grid of panels and draws through ``plot()``,
not through ``render(sim, ax)``. It reads the keys the trial published, which follow
the maps in the cost:

- one bound: the unsuffixed ``J_signed``, ``Doptim``, ``validity_length_m``,
  ``roptim``, ``L_ref`` (``h_obs``) and the three counts, as before;
- two bounds: one bracket per bound on ``J_signed_minimal`` and
  ``J_signed_maximal``, and each bound's ``Doptim`` against its own length, its
  counts and its Eq. 4 verdict side by side, read at the trial the search
  returned, where the run reads Eq. 4. The two roots, ``Delta`` and the combined
  value are in the report and not in the trials: pass ``roots=report.extra["roots"]``
  to ``plot()`` to write them on the card. A bound weighted zero is drawn and
  marked outside the verdict;
- one state with both maps: the minimal map in the cost, and the maximal map
  scored as a validation (``_maximal_validation``) drawn beside it, with no verdict.

What to publish
---------------

Publish the ratio, not the conductivity. When the search moves the homogeneous
conductivity alone, ``flow.param.K.field.value`` written as a value, the report
carries the derived values of Table 1 of the paper in its ``extra`` and the CLI
prints them on one line: ``k_over_r``, ``k_optim_m_s``, and, when the backend
serves a saturated thickness, ``d_sat_m``, ``t_over_r_m`` (``T/R``, a length) and
``t_optim_m2_s``. A search on any other parameter gets none of them, because the
network criterion drives any parameter and a thickness divided by ``R`` is not
``K/R``. The note warns when ``d_sat_over_d`` exceeds one half: an aquifer that
runs nearly full makes ``T/R`` depend on the imposed thickness. State the
recharge series beside the number: the conductivity inherits it entirely, and
changing reanalysis moved it by +3, +25 and -28 per cent on the three catchments
the theory page reports.

What the code does publish, and what belongs in the paper beside the value, is
the diagnostic set above: ``D_so`` and ``D_os``, the cost ``J`` with its signed
form ``J_signed``, ``Doptim`` and ``roptim`` with ``roptim_valid``. See the
section on known biases of the theory page before reusing any of them.

And state the density of the mapped network beside the value, because the bias
scales with it. On the Nancon the map is the permanent network alone, 0.70 km
per km2 inside the catchment, and the calibrated conductivity came out 3.3
times the prior the project declares, inside the documented factor of 2.7 to
7.5 for a thinned network.
