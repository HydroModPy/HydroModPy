Four calibrations to start from
===============================

Four complete configurations, shipped as files rather than as snippets, so
that a copy is a copy and not a transcription. Each one loads: a unit test
validates all four on every commit, which is what keeps them true after a key
is renamed.

Each is an overlay. It carries the search and inherits the catchment, the data
and the solver from the project it points at, so the model that is calibrated
and the model that is run are one description. The project has to declare the
parameters the overlay moves, in ``[flow] param_list`` and ``[flow.param.<id>]``;
a calibration cannot search over a property the model does not have. Copy one
next to your ``project.toml`` and run it:

.. code-block:: bash

   hmp calibrate --check calibration_single_gauge.toml   # nothing solves
   hmp calibrate calibration_single_gauge.toml

Pick by what the site actually offers.

.. list-table::
   :header-rows: 1
   :widths: 28 34 38

   * - Recipe
     - Use it when
     - What it decides
   * - :ref:`One gauge <recipe-single-gauge>`
     - One discharge record, one property to identify.
     - The bounds, the metric, and how much of the record is burn-in.
   * - :ref:`Several targets <recipe-multi-objective>`
     - A gauge, a piezometer and a lake all constrain the same model.
     - What share of the cost each target carries.
   * - :ref:`A published method <recipe-protocol>`
     - The catchment is mapped but poorly gauged.
     - Almost nothing: the method is named, not retyped.
   * - :ref:`The same method, by hand <recipe-staged-by-hand>`
     - The two stages need to say more than the protocol does.
     - Every stage, criterion and override, spelled out.

.. _recipe-single-gauge:

One parameter, one gauge, one metric
------------------------------------

The shape almost every calibration starts from. A hydraulic conductivity is
swept over a bounded range and scored against one observed discharge series.

Two lines carry most of the modelling decision. ``bounds`` states what the site
could plausibly be, and a range far wider than the evidence buys a search over
a region the data already excludes. ``scoring_window.start`` is the first date
scored, which leaves the head of the record out, because that stretch is still
forgetting the initial condition; move it later until the objective stops
moving. A date names the same span at any time step, where a count of samples
does not.

.. literalinclude:: ../recipes/calibration_single_gauge.toml
   :language: toml

.. _recipe-multi-objective:

Several targets, weighted against each other
--------------------------------------------

A catchment rarely offers one observation. Here the model is scored at once on
the outlet hydrograph, on a piezometer, and on a lake level, each with its own
metric and its own share of the cost.

The weights are the decision this file exists to make explicit. They sum to
1.0, so each reads directly as a share: the hydrograph carries 65 %, the
piezometer 25 %, the lake 10 %. Write them any way you like; only the ratios
matter to the search, and summing to one is what makes them readable.

``normalize_cost`` matters here and did not in the previous recipe. An RMSE on
heads is in metres, an NSE cost is dimensionless, and adding them raw lets the
unit set the weighting instead of the weight.

``observes`` is what makes the weighting mean anything. It names a station the
project loaded; the record is aligned on the simulated timestamps, and the block
scores that. Without it a block can only be scored against ``observed_values``,
a positional vector transcribed into the file with no dates on it, so the one
route that can weight several targets was also the one that could not read a
real observation.

Two consequences follow. A ``scoring_window`` becomes applicable, because the
samples now carry dates to cut on; it is still refused for any output scored
positionally, by name. And each block reports ``<output>.n_paired``, how many
dated samples the alignment kept: a weight of 65 % resting on three surviving
days is not what the file says it is, and that is where it shows.

.. literalinclude:: ../recipes/calibration_multi_objective.toml
   :language: toml

.. _recipe-protocol:

A published method, named instead of retyped
---------------------------------------------

Conductivity from the extent of the hydrographic network, storage from the
hydrograph. See :doc:`stream-network-calibration` for what the criterion
measures and :cite:`abherve2023` for the method.

``protocol = "matching_hydrographic_network"`` writes the whole assembly: two
stages, their criteria, the regime that makes the first steady and the second
transient, and the objective block wiring. What stays in the file is what
belongs to the site.

.. literalinclude:: ../recipes/calibration_matching_hydrographic_network.toml
   :language: toml

A file cannot both name a protocol and declare its own ``[[calibration.phases]]``
or ``[[calibration.objective_blocks]]``: that is two answers to one question,
and it is refused rather than silently resolved. Drop the protocol to write the
stages by hand, or drop the stages to let the protocol write them. The long
form, and the deviation it buys that a name cannot express, are in
:doc:`stream-network-calibration`;
``examples/projects/04_streamflow_intermittence_in_transient/run_calibration_by_hand.toml``
ships the faithful long form against the same catchment as the protocol next door.

Every option under ``[calibration.protocol]`` has a default that reproduces the
published method, so the shortest form of this recipe is one line:

.. code-block:: toml

   [calibration]
   protocol = "matching_hydrographic_network"

The engines are not part of the method. ``steady_method`` and
``transient_method`` take any registered optimizer, so the same two criteria can
be walked by a bisection, by Nelder-Mead, or by Optuna without changing what is
being calibrated.

Read what a name expands to without running it:

.. code-block:: bash

   hmp calibrate calibration_matching_hydrographic_network.toml --expand

It prints the whole ``[calibration]`` section the name stands for, as TOML: the
parameters and outputs the file declares, the ``[calibration.outputs]`` entry
the transient stage adds when the gauging station is known from the file alone,
and the two stages with their objective blocks. Pasted in place of the
protocol, it runs the same stages. When the protocol comes from a
``base_config``, the header adds that a file pasting it under that same base
also writes ``protocol__delete = true``. A file that loads several stations
keeps the protocol's older form for the transient stage, a single ``variable``
and ``objective`` naming no output.

The transient stage prints with a ``scoring_window`` even when the file writes
none. Its first year starts from an initial condition the run did not produce,
so the protocol scores it from one year after the ``start_datetime`` of
``[simulation.time]``, for every block the stage scores. A ``scoring_window`` under
``[calibration.protocol]`` replaces that start, and one under ``[calibration]``
removes it; a window starting on the run's own first day scores the spin-up
year too. A date in a protocol window that does not parse is refused when the
file is read. A run of one year or less has nothing
past its spin-up and is scored whole. The protocol record lists the rule as the
``spin_up_year`` departure: the published application scores June to October
of one drought year, a window no default can carry.

.. _recipe-staged-by-hand:

The same method, written out instead of named
---------------------------------------------

The recipe above is the short form. This one is the long form of the same
method, generic and ready to copy next to any project: no ``protocol`` line,
every stage, criterion and override spelled out instead.

Two phases, chained by ``depends_on`` and ``freeze_on_success`` exactly as the
protocol writes them. ``regime = "steady"`` and ``regime = "transient"`` say
which model each stage runs, in place of overriding the flow regime and the
time grid by hand. Stage one moves K alone, steady state, scored by
``distance_gap`` on a ``support = "network"`` output, walked by a bisection to
the root the criterion crosses. Stage two moves Sy alone, monthly transient, K
frozen, and scores it on two blocks: ``nse_log`` on the gauge, declared as a
``support = "point"`` output with ``observes``, next to ``distance_gap`` on the
same network output. That second block is the one thing the named protocol
does not offer; writing the stages out is what makes room for it.

Stage two gives the two blocks a share table, ``{ hydrograph = 0.8,
network_share = 0.2 }``, instead of a weight on each block: this stage sets
its own balance, normalised to sum to one, without touching what another
phase might read from the same blocks. ``network_share`` is the network gap
with ``normalize_cost = true``, divided by the output's ``validity_length``
(Eq. 4, ``"auto"`` = 2 h_obs), so both blocks are pure numbers and a share is
a share rather than an exchange rate between metres and an efficiency. Stage
one keeps the gap in metres, where its interval is read in mesh cells. Stage
two also names no ``method``: the hydrograph block is not signed, so the phase
has a cost to minimise and gets ``scipy_nelder_mead`` on its own;
``--list-phases`` prints the choice and why.

``scoring_window.start`` on stage two leaves the spin-up year out of both
blocks. The hydrograph keeps its months from that date on. The network output
reads one state, dated at the stamp that closes its period, the last month
here, and the window has to hold that stamp: ``hmp calibrate --check`` names
both when it does not. ``time = "2003-08-15"`` on the output would read the
state of August 2003 instead, the period that holds that date.

.. literalinclude:: ../recipes/calibration_staged_by_hand.toml
   :language: toml

Start here when a stage of the published method needs to say more than its
name can, or to read in one place what ``protocol =
"matching_hydrographic_network"`` expands into. The two files agree on every
stage, criterion and override; only the second objective block differs.
``examples/projects/04_streamflow_intermittence_in_transient/run_calibration_composite.toml``
weights the network and the hydrograph in one transient phase against a real
catchment.

Checking before the solver starts
---------------------------------

A calibration is hours of solver time, so the last thing you want is a typo
found at hour three. One flag runs every static check and solves nothing:

.. code-block:: bash

   hmp calibrate --check project.toml

.. code-block:: text

   ERROR   [calibration.parameters.K]: path 'flow.param.Kh.field.value' is not a
           value this configuration carries. `hmp config targets` lists them.
   ERROR   [[calibration.objective_blocks]] 'hydrograph': uses_outputs names ghost,
           which [calibration.outputs] does not declare. Declared: outlet.
   calib.toml: 2 error(s), 0 warning(s).

Every check runs, so a file with three mistakes comes back with three findings
and takes one pass to fix. It checks that each parameter path is a value the
configuration actually carries, that the bounds are ordered and inside the
physical range the registry enforces, that a stream geometry is where the run
will look for it, and that every name a block or a phase uses is declared. It
exits on the config code when anything is wrong, so a script can gate on it.

It also faces each search with what its engine says it can be handed. A
bisection moves one parameter, walks a log10 variable and drives a signed
residual to zero; hand it two parameters, a linear one, or a search scored on
``nse_log``, and the refusal used to arrive when that phase started, after the
phases before it had spent their whole budget.

What it cannot see it does not pretend to: an observed record is loaded by the
data step, which needs a delineated catchment, so preflight checks the names a
file declares against each other and leaves the loading to the run.

It also warns, rather than refuses, when an objective scored only on a network
output moves more than one parameter, such as ``K`` and the aquifer thickness
together: the two act on the criterion only through their product
:math:`T = K \cdot d`, so they form a ridge in that cost and the search returns
one point of the ridge, not an identifiable pair. Freeze every parameter on
that objective but one, or add an output this search does not share the ridge
on, such as the hydrograph.

Finding what a project can calibrate
------------------------------------

A parameter is declared by a dotted path into the configuration, and guessing
one is not a workflow. Ask the project:

.. code-block:: bash

   hmp config targets project.toml

.. code-block:: text

   path                                current      unit  physical range
   flow.bc.drainage.value                0.001      m2/s  -
   flow.param.K.field.value              5e-05       m/s  1e-14 .. 100
   flow.param.Ss.field.value             1e-05       m-1  1e-12 .. 0.001
   flow.param.Sy.field.value              0.05         -  0.0001 .. 0.5
   flow.sinks_sources.recharge.values         0    mm/day  -

The list comes from the resolved configuration, so it names the parameters and
boundaries this project actually declares, not everything the schema could hold.
The three columns are what a bound is written from: where the value sits today,
in what unit, and the range the physical registry will refuse outside of. A
range shown as ``-`` means the registry does not know this identifier, so
nothing will check the bounds for you.

The aquifer geometry itself is calibrable on the two scalar depth models, and
the catalogue shows only the field the project's own ``domain.depth_model``
kind exposes, under its short name:

.. list-table::
   :header-rows: 1
   :widths: 18 22 15 15 30

   * - kind
     - name
     - space
     - prior
     - registry range
   * - ``constant_thickness``
     - ``thickness``
     - log
     - ``log_uniform``
     - 0 to 10 000 m
   * - ``flat_substratum``
     - ``substratum_elevation``
     - linear
     - ``uniform``
     - -500 to 9000 m

.. code-block:: toml

   [calibration.parameters.thickness]
   bounds = [5.0, 300.0]

``thickness`` is searched in log space because it enters :math:`T = K \cdot d`
as a factor, exactly like :math:`K`, and the sensitivity range of
:cite:`abherve2023` spans nearly two decades, 5 to 300 m.
``substratum_elevation`` is searched in linear space instead, because an
elevation can be negative and has no natural zero. Neither field defaults its
search bounds from the registry range shown above: the range only guards a
declared bound, it is not a box to search blindly, so ``bounds`` is required
in the file for both, the same rule ``K`` already follows. The raster depth
models, ``raster_substratum`` and ``raster_thickness``, are not searchable and
list nothing: their raster is a map of the site, not a scalar, so compare one
run per raster instead of calibrating one.

Moving the thickness changes :math:`T = K \cdot d` exactly as moving :math:`K`
does. On the stream-network criterion, searching :math:`K` alone at a fixed
thickness identifies :math:`T/R`, the quantity :doc:`stream-network-calibration`
describes; searching the thickness alone at a fixed :math:`K` identifies the
same ratio from the other factor. Searching both together on that criterion
alone is equifinal, because the criterion only ever sees their product: it
takes another observation, such as the hydrograph, to separate them.

A thickness search re-runs the pipeline from ``setup_process`` for every
trial, because the domain the mesh is built on depends on the depth model; it
never rebuilds the mesh itself, so a raster or a grid change still needs a new
run rather than a calibration.

Add ``--json`` for the same catalogue as machine-readable records.

Reading the value the search returns
------------------------------------

A calibration returns one number per parameter, and a number on its own says
nothing about its own standing. The report adds two things read off the trials
the search already ran, so they cost no extra model runs.

**How wide the optimum is.** ``parameter_intervals`` gives, per parameter, the
range of sampled values whose cost stayed within a tolerance of the best,
together with how many trials that was out of how many. Read it as "the
search could not tell these apart", not as a confidence interval: it rests on
no error model, and a parameter the search never varied far has a narrow range
because nothing else was tried. See :doc:`calibration-uncertainty` for what the
interval means, its other two methods, and when to change the default.

The flag to read first is whether the range runs into a search bound. There the
record did not determine the parameter, the search simply ran out of room, and
widening the bounds is the next step rather than reporting the edge as a result.
The run says so in one line:

.. code-block:: text

   K = 3.1e-06, and 14 of 60 trials scored within 0.081 of the best over
   [2.4e-06, 4.8e-06].
   Sy = 0.35, and 31 of 120 trials scored within 0.12 of the best over
   [0.19, 0.35]; that range runs into the upper search bound.

Left unwritten, the tolerance follows what is scored: five per cent of the
best cost for an ordinary criterion, or one mesh cell, in metres, for a phase
(or a whole calibration with no phases) scored only by network distances such
as ``distance_gap``. A stream cannot move by less than a cell, and five per
cent of a criterion solved at zero is always zero. ``hmp calibrate
--list-phases`` prints the width in use and where it came from. Write it only
to choose otherwise:

.. code-block:: toml

   [calibration.uncertainty]
   method = "cost_profile"
   mode = "relative"
   tolerance = 0.05

``mode = "relative"`` is refused on a phase scored only by network distances,
because there is no fraction of a zero cost to take. State the width in the
unit of the cost there instead, which is the default already, or write it to
depart from the mesh cell:

.. code-block:: toml

   [calibration.uncertainty]
   mode = "absolute"
   tolerance = 25.0        # metres of network offset

**How the members were made addable.** ``[calibration.aggregate]`` names it
rather than leaving it implicit:

.. code-block:: toml

   [calibration.aggregate]
   weighting = "manual"        # or "error": one over sigma
   nested_gauges = "total"     # or "incremental" on imbricated catchments
   min_samples = 30            # refuse a member scored on fewer pairs
   on_member_failure = "veto"  # or "drop", which records what was left out

Two questions the word "weight" runs together. Whether an error is large *for
what the instrument can resolve* is a property of the measurement, not a
decision. What matters more between the outlet and the reservoir is a decision,
and yours. The cost is the product of both.

``weighting = "error"`` divides each residual by what its gauge resolves, so the
members become pure numbers before the weights apply. It needs a residual metric
and a loaded record carrying an error model, and is refused without both: an
efficiency score has no residual to divide, and a vector typed into the file
carries no sigma.

``nested_gauges`` matters when two gauges sit on imbricated catchments. Nothing
is double counted, but the residuals are statistically dependent and no standard
correction exists. ``"total"`` scores each gauge against its own full drained
area, which is what a gauge measures; ``"incremental"`` scores the downstream one
on what its own reach adds, which is the only mechanisable way to make the two
independent. The overlap is measured and reported either way.

**Whether two parameters were told apart.** ``correlated_parameters`` lists the
pairs that moved together across the whole search to hold the same cost. Such a
pair was not identified: the search stopped somewhere on a ridge and reported
that point as a minimum. The sign is kept, because it says which way the
trade-off ran.

Convergence and budget
-----------------------

Converging means meeting the engine's own stopping rule, not spending the
budget. ``bisection`` stops on the bracket width, ``log10(1 + rel_tol)``
in the searched variable, and ``scipy_nelder_mead`` on ``xatol``. Every other
built-in engine (``random_search``, ``optuna``, ``cma_es``, ``grid``,
``gp_mapping``, ``scipy_de``, ``da_mh_gp``) declares no tolerance option, so
spending its budget is its own rule and it is always reported as converged.

The budget of a ``bisection`` is known before the first solve, so its
``max_iter`` defaults to ``"auto"``. With ``d`` the declared interval in
decades, ``t = log10(1 + rel_tol)``, ``S`` sweep points (two when
``sweep_points`` is zero), ``s = d / (S - 1)`` and ``E = bracket_expand``, a
root inside the bounds costs ``S + ceil(log2(s / t))`` evaluations and one
found after ``e`` expansions ``S + 2e + ceil(log2(1 / t))``; ``"auto"`` budgets
the largest. On ``[1e-7, 1e-3]`` with seven sweep points and one per cent that
is 15 inside the bounds and 23 at worst. A declared number below the nominal
count is refused by ``hmp calibrate --check`` and again before the first solve;
one below the worst case is announced with the number of expansions it covers.
If the budget still runs out, the search is granted exactly the halvings its
bracket still needs, once, with a warning, provided they fit in half the budget.

Every other engine cannot count what it needs: ``"auto"`` gives it 100, and it
gets no extension. When ``max_iter`` runs out before a judged engine's rule is
met, ``report.extra["search"]["converged"]`` is ``False``, the session closes
as ``partial``, the phase freezes nothing, and a phase declaring
``depends_on`` on it is refused rather than run against an unfrozen value. The
fix is to raise ``max_iter`` or loosen the tolerance, not to read the last
trial as the answer; a re-run replays the trials already solved from the cache.

Every run through the ordinary path carries in its report:

``extra["search"]``
   ``{converged, stopping_rule, max_iter, extension, n_evaluations}``, on
   every calibration, whichever engine ran.

``extra["bracket"]``
   ``{parameter, low, high, relative_width, closed}``, in physical units,
   once a bisection has found a sign change. It is what the search proved
   about the root, and it is distinct from ``parameter_intervals`` above,
   which reads a tolerance on the trials after the fact rather than the
   search's own bracket.

A bisection's evaluation budget is the sweep points (two, when
``sweep_points = 0``) plus ``ceil(log2(sweep step in decades / log10(1 + rel_tol)))``.
On bounds of ``[1e-7, 1e-3]`` with seven sweep points and ``rel_tol = 0.01``
that is 15 evaluations. A root outside the declared bounds costs two more
evaluations per decade of expansion, plus the halvings a wider bracket then
needs.

The trial a bisection returns is the lowest-cost **completed trial inside the
final bracket**, ends included; a rejected trial that set a bracket end can
still be the closest to zero without being returned, because it lies outside
what the bracket closed on. Costs within a tight float tolerance count as a
tie, and a tie goes to the trial nearest the middle of the bracket. A trial
outside the bracket is returned only when no completed trial lies inside it,
which happens when a rejected trial set the bracket's own ends, and a warning
says so.

Why the mesh is not a parameter
-------------------------------

A mesh resolution or a refinement setting cannot be declared under
``[calibration.parameters]``; the file is refused with the reason. The
stream-network criterion is normalised by cell size, so refining the mesh moves
the yardstick the search is scored against, and a search that optimises it
improves the number by changing the ruler.

A mesh question is a convergence question, and it is answered by a sweep: one
run per mesh, compared, and read for convergence rather than for a best score.

.. code-block:: toml

   # mesh_sweep.toml
   [workflow]
   mode = "comparison"

   [comparison]
   comparison_id = "mesh_convergence"
   base_simulation_config = "project.toml"
   output_root = "outputs/mesh_convergence"
   reference_simulation = "mesh_250"

   [[comparison.simulation]]
   id = "mesh_500"
   label = "target cell size 500 m"
   solver = "modflow6"

   [comparison.simulation.overlay.mesh_catchment.zone_meshing]
   global_size = 500.0

   [[comparison.simulation]]
   id = "mesh_350"
   label = "target cell size 350 m"
   solver = "modflow6"

   [comparison.simulation.overlay.mesh_catchment.zone_meshing]
   global_size = 350.0

   [[comparison.simulation]]
   id = "mesh_250"
   label = "target cell size 250 m"
   solver = "modflow6"

   [comparison.simulation.overlay.mesh_catchment.zone_meshing]
   global_size = 250.0

   # What the three meshes are compared on. The seepage extent is the quantity
   # the stream-network criterion reads, so it is the one whose mesh sensitivity
   # decides how fine the calibration has to be.
   [[comparison.observable]]
   name = "seepage_map_last"
   variable = "seepage_areas"
   support = "map"
   time = "last"
   unit = "-"

   [[comparison.observable]]
   name = "head_map_last"
   variable = "watertable_elevation"
   support = "map"
   time = "last"
   unit = "m"

.. code-block:: bash

   hmp run mesh_sweep.toml

A cell may be a whole calibration rather than a single run, which is what a
structural sweep actually is: one complete calibration per mesh, each with its own
plan. Declare it in the cell's overlay:

.. code-block:: toml

   [comparison.simulation.overlay.workflow]
   mode = "calibration"

   [comparison.simulation.overlay.calibration]
   protocol = "matching_hydrographic_network"

The child is materialised the same way and dispatched by ``hmp run`` on its own
``[workflow] mode``, so the cohort machinery does not need to know which kind of
cell it built. What it must not do is rank them: the criterion is normalised by
cell size, so the cheapest cost belongs to the finest mesh whatever the
hydrogeology.

Read the spread across the three as the numerical error on whatever you report,
and refine until it stops moving. Calibrate on the coarsest mesh whose answer no
longer changes: a finer one buys solve time, not information. Running the
calibration on each mesh in turn and keeping the K that scored best is the same
circularity in a longer form, because the criterion those K are compared on is
itself normalised by cell size.
