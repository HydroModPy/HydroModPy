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
   roptim_max          = 2.0
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

   [calibration.phases.optimizer_kwargs]
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

   [calibration.phases.optimizer_kwargs]
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
It inherits the project next door, which names the protocol, so it starts by
dropping the name:

.. code-block:: toml

   base_config = "project.toml"

   [calibration]
   protocol__delete = true

Run ``hmp calibrate project.toml --list-phases`` in that directory and the two
stages the name expands to are the two stages that file writes out. Nothing
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
   x        = 389285.910
   y        = 6816518.749

   [[calibration.objective_blocks]]
   name         = "network_extension"
   metric       = "distance_gap"
   uses_outputs = ["seepage_network"]

   [[calibration.objective_blocks]]
   name         = "hydrograph"
   metric       = "nse_log"
   uses_outputs = ["gauged_discharge"]
   warmup       = 12

   [[calibration.phases]]
   name             = "transient_storage"
   max_iter         = 30
   tolerance        = 0.05
   parameters       = ["Sy"]
   objective_blocks = { hydrograph = 100, network_extension = 1 }
   depends_on       = "steady_conductivity"
   regime           = "transient"

Four things in there are not free choices.

``support = "point"`` with ``observes``, for the gauge
   The single-metric route declares no output, so a stage that scores two
   criteria has to name the gauge as one. That form reads what the
   single-metric route reads, which is what keeps the two costs comparable:
   the station's own cell where the loader placed one, with the runoff of
   ``[data.runoff]`` added over the area that cell drains, and the
   whole-catchment series where it placed none, with the basin's runoff added.
   A discharge station is deliberately never placed by the coordinates written
   beside it, so the second case is the ordinary one, and the run logs one line
   naming the station when it takes it. The same target written
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

``warmup`` rather than ``scoring_window``, for the spin-up
   A window cuts a loaded record on its dates. A network output is scored on
   the pair ``(D_so, D_os)``, which carries none, so a phase declaring a window
   beside a network block is refused rather than scored over the whole run
   under the name of a windowed one. A count of samples applies to the block
   that has a record, and twelve monthly samples are the same span the window
   would have named.

The network block, in transient, scores one instant
   A network output reads exactly one state: ``time = "last"`` (default) or
   ``"first"``. ``"all"`` and a list of ISO dates are refused at configuration
   load, so a phase can no longer name a date here and have the criterion score
   the last stress period instead of it. The block compares one month to the
   mapped network, the last of the simulated record; pick that month with the
   phase's ``end_datetime``, not with ``time``. A transient comparison of the
   minimal and maximal extents is a separate mode being designed. Scoring the
   seasonal extension itself rather than one instant is the method of
   :cite:`abherve2024headwater`, and it needs an intermittence record.

``objective_blocks`` as a share table, not a list
   The two costs are in different units: ``distance_gap`` is metres and
   ``1 - nse_log`` is a pure number. ``normalize_cost`` is refused on both, for
   opposite reasons, the first fitting no record to take a spread from and the
   second being already dimensionless. A table, ``{ block = share, ... }``,
   gives the phase its own balance between the two instead of a weight
   declared once on the block itself, which would also apply to any other
   phase that reads it. Shares are normalized to sum to one, so the trial cost
   above is ``0.0099 * |gap| + 0.990 * (1 - NSElog)``. Set the ratio against
   the magnitudes the first stage published rather than by halves, and read
   ``network_extension.total`` and ``hydrograph.total``, which every trial
   reports, to see what it bought.

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

Measured on the Nancon
----------------------

The two files of example 04 were run side by side on 2026-09-23, same code and
same machine, after the stress-period alignment fix: a monthly stamp closes its
month, so the gauge is compared with the month the stamp ends (commit
``e6c5e50f5``). A score taken before that fix is not comparable with these.

.. list-table::
   :header-rows: 1
   :widths: 22 39 39

   * -
     - ``project.toml``, the protocol
     - ``run_calibration_by_hand.toml``
   * - stage one
     - ``K`` = 9.763e-05 m/s, signed gap 2.7 m, 15 trials
     - identical, to the trial
   * - stage two
     - ``Sy`` = 0.047, NSElog 0.921, 6 trials
     - ``Sy`` = 0.063, NSElog 0.898, 14 trials
   * - December network gap
     - not scored
     - 17.3 m

Scoring the network as well as the gauge moves the storage by about a third,
from 0.047 to 0.063, and costs 0.023 of NSElog. Over the fourteen trials the
gap took four values, from 24.2 m at ``Sy`` = 0.042 to 15.2 m at 0.098: the
simulated network retracts by whole cells, which sets the region, and the
hydrograph does the fine work inside it. Neither term rode along: the network
term weighed 0.15 to 0.24 of the trial cost and the hydrograph term 0.09 to
0.14. Which of the two storages suits the site is a judgement about the site,
not about the machinery, and that is the point of being able to write the
stage out.

The validity indicator does not clear its bound on this catchment, and every
trial says so. ``roptim`` is the agreement between the two networks in
reference lengths, valid at 2 and under. Here it runs from 1.9 to 6.4 over the
stage one sweep, 2.44 at the retained ``K``, and 2.50 to 2.56 in the transient
stage. The agreement is therefore coarser than the mesh. This qualifies the
calibrated value rather than refuting it: a ``K`` read off this example is a
demonstration, not a number to cite, and the ratio ``K/R`` is what to publish.
Two diagnostics of the same trials say where it comes from.
``alpha_obs_closure_catchment`` is 0.83 against 0.90, and 55 per cent of the
mapped stream cells lie outside the delineated catchment, in a buffer where
nothing requires a cell to descend into the network. Clipping the mapped
network to the catchment is what would move them.

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

``roptim`` and ``roptim_valid``
   The validity indicator of Equation 4, against the ``roptim_max`` bound (two
   by default), recorded on every trial. It **qualifies** the result and does
   not withhold it: a violation warns and the value comes back, unless you set
   ``on_roptim_violation = "error"``, which raises instead. And it measures
   agreement, not correctness, so do not read it as a quality score of the
   model.

``roptim_verdict``
   The bound of Equation 4, read once, on the trial the search returns, the
   way the paper reads it: "At this point" (HESS p. 3225), not on the way
   there. A report entry per network output,
   ``{value, bound, L_ref, Doptim, valid}``; a ``roptim`` that is not a
   number, an empty simulated network at the returned trial, counts as a
   violation. With ``on_roptim_violation = "error"`` the raise happens after
   the session is saved, so every trial is still on disk, and a staged
   calibration stops there rather than freezing an unqualified value into a
   dependent phase.

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

Eight figures are registered for this method: ``downslope_distance_crossing``,
``bisection_bracket_trace``, ``parameter_cost_profile``,
``matching_hydrographic_network_card``, ``seepage_network_reference_overlay``,
``seepage_network_confusion_map``, ``downslope_distance_map`` and
``hydrograph_log_nse``.

All eight are declared, never scripted. List them in ``[display].figures`` of
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

A ninth figure, ``roptim_validity_chart``, compares the calibrated agreement of
SEVERAL catchments, and a run holds one. It refuses a run-driven render by name
rather than drawing one point, and it is fed per-site records directly.

``matching_hydrographic_network_card`` is a grid of panels and draws through ``plot()``,
not through ``render(sim, ax)``.

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
