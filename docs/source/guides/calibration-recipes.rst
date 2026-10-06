Four calibrations to start from
===============================

Four complete configurations, shipped as files rather than as snippets, so
that a copy is a copy and not a transcription. Each one loads: a unit test
loads all four, which is what keeps them true after a key is renamed.

Each is an overlay. It carries the search and inherits the catchment, the data
and the solver from the project it points at, so the model that is calibrated
and the model that is run are one description. The project has to declare the
parameters the overlay moves, in :toml:`flow.param_list` and under
``[flow.param.<id>]``. A calibration cannot search over a property the model
does not have. Copy one next to your ``project.toml`` and run it:

.. code-block:: bash

   hmp calibrate calibration_single_gauge.toml --check   # nothing solves
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
     - The bounds, the metric, and how much of the record is spin-up.
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

Two lines carry most of the modelling decision. :toml:`bounds|calibration.parameters.K.bounds`
states what the site could plausibly be, and a range far wider than the
evidence buys a search over a region the data already excludes.
:toml:`start|calibration.scoring_window.start` is the first date scored, which
leaves the head of the record out, because that stretch is still forgetting the
initial condition. Move it later until the objective stops moving. A date names
the same span at any time step, where a count of samples
(:toml:`calibration.warmup_periods`) does not. The two are mutually exclusive.

.. literalinclude:: recipes/calibration_single_gauge.toml
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
matter to the search, because the weights are normalised to sum to one.
Summing to one is what makes them readable.

:toml:`calibration.objective_blocks.normalize_cost` matters here and did not in
the single-gauge recipe. An RMSE on heads is in metres, an NSE cost is
dimensionless, and adding them raw lets the unit set the weighting instead of
the weight. On an efficiency score the key is refused, because that cost is
already a pure number.

:toml:`calibration.outputs.<name>.observes` is what makes the weighting mean
anything. It names a station the project loaded; the record is aligned on the
simulated timestamps, and the block scores that. Without it a block can only be
scored against :toml:`calibration.outputs.<name>.observed_values`, a positional
vector transcribed into the file with no dates on it, so the one route that can
weight several targets was also the one that could not read a real observation.

Two consequences follow. A :toml:`calibration.scoring_window` becomes
applicable, because the samples now carry dates to cut on; it is still refused
for any output scored positionally, and the refusal names the output. And each
block reports ``<output>.n_paired``, how many dated samples the alignment kept:
a weight of 65 % resting on three surviving days is not what the file says it
is, and that is where it shows.

.. literalinclude:: recipes/calibration_multi_objective.toml
   :language: toml

How the members of the cost are made addable
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:toml:`calibration.aggregate` names how the blocks of a multi-target cost are
added, rather than leaving it implicit:

.. code-block:: toml

   [calibration.aggregate]
   nested_gauges = "incremental"
   min_samples = 30

.. hmp-params::

   calibration.aggregate.weighting
   calibration.aggregate.nested_gauges
   calibration.aggregate.min_samples
   calibration.aggregate.on_member_failure

The word "weight" runs two questions together. Whether an error is large *for
what the instrument can resolve* is a property of the measurement, not a
decision. What matters more between the outlet and the reservoir is a decision,
and yours. The cost is the product of both.

:toml:`weighting = "error"|calibration.aggregate.weighting` divides each
residual by what its gauge resolves, so the members become pure numbers before
the weights apply. It needs a residual metric and a loaded record carrying an
error model, and is refused without both: an efficiency score has no residual to
divide, and a vector typed into the file carries no sigma.

:toml:`calibration.aggregate.nested_gauges` matters when two gauges sit on
imbricated catchments. Nothing is double counted, but the residuals are
statistically dependent and no standard correction exists. ``"total"`` scores
each gauge against its own full drained area, which is what a gauge measures;
``"incremental"`` scores the downstream one on what its own reach adds, which is
the only mechanisable way to make the two independent. The overlap is measured
and reported either way.

.. _recipe-protocol:

A published method, named instead of retyped
---------------------------------------------

Conductivity from the extent of the hydrographic network, storage from the
hydrograph. See :doc:`calibrate-on-the-stream-network` for what the criterion
measures and :cite:`abherve2023` for the method.

:toml:`protocol|calibration.protocol.name` ``= "matching_hydrographic_network"``
writes the whole assembly: two stages, their criteria, the regime that makes the
first steady and the second transient, and the objective block wiring. What
stays in the file is what belongs to the site: the two parameters with their
bounds, and the network output with the path of the mapped network.

.. literalinclude:: recipes/calibration_matching_hydrographic_network.toml
   :language: toml

A file cannot both name a protocol and declare its own
:toml:`calibration.phases` or :toml:`calibration.objective_blocks` that differ
from what the protocol writes: that is two answers to one question, and it is
refused rather than silently resolved. Drop the protocol to write the stages by
hand, or drop the stages to let the protocol write them. The long form, and the
deviation it buys that a name cannot express, are in
:doc:`calibrate-on-the-stream-network`;
``examples/projects/04_streamflow_intermittence_in_transient/run_calibration_by_hand.toml``
ships the faithful long form against the same catchment as the protocol next door.

Every option under ``[calibration.protocol]`` has a default, so the declaration
itself is one line. The file still declares the two parameters and the network
output, because the protocol moves them and scores on it:

.. code-block:: toml

   base_config = "step4_transient.toml"

   [workflow]
   mode = "calibration"

   [calibration]
   protocol = "matching_hydrographic_network"

   [calibration.parameters.K]
   bounds = [1e-7, 1e-3]

   [calibration.parameters.Sy]
   bounds = [5e-3, 0.35]

   [calibration.outputs.seepage_network]
   support = "network"
   stream_geometry_path = "nancon_stream_network.gpkg"

The defaults do not all reproduce the publication. A few depart from it on
purpose, such as the rasterisation of the mapped network and the spin-up year
that stage two leaves out. ``hmp calibrate --check`` prints each departure
before the run, and ``-v`` adds the stages, the references and every reading of
the paper this implementation makes.

The engines are not part of the method. :toml:`calibration.protocol.steady_method`
and :toml:`calibration.protocol.transient_method` take the name of any registered
optimizer, so the same two criteria can be walked by a bisection, by Nelder-Mead,
or by Optuna without changing what is being calibrated. ``--check`` faces the
choice with what the engine can be handed.

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
and ``objective`` naming no output. ``--expand`` is refused together with
``--phase``, ``--list-phases`` or ``--check``.

The transient stage prints with a ``scoring_window`` even when the file writes
none. Its first year starts from an initial condition the run did not produce,
so the protocol scores it from one year after the
:toml:`start_datetime|simulation.time.start_datetime`, for every block the stage
scores. A :toml:`calibration.protocol.scoring_window` replaces that start, and
one under :toml:`calibration.scoring_window` removes it; a window starting on
the run's own first day scores the spin-up year too. A date in a protocol window
that does not parse is refused when the file is read. A run of one year or less
has nothing past its spin-up and is scored whole, and ``--check`` says so. The
protocol record lists the rule as the ``spin_up_year`` departure: the published
application scores June to October of one drought year, a window no default can
carry.

.. _recipe-staged-by-hand:

The same method, written out instead of named
---------------------------------------------

The recipe above is the short form. This one is the long form of the same
method, generic and ready to copy next to any project: no ``protocol`` line,
every stage, criterion and override spelled out instead.

Two phases, chained by :toml:`depends_on|calibration.phases.depends_on` and
:toml:`freeze_on_success|calibration.phases.freeze_on_success` exactly as the
protocol writes them. :toml:`regime = "steady"|calibration.phases.regime` and
``regime = "transient"`` say which model each stage runs, in place of
overriding the flow regime and the time grid by hand. Stage one moves K alone,
steady state, scored by ``distance_gap`` on a ``support = "network"`` output,
walked by a bisection to the root the criterion crosses. Stage two moves Sy
alone, monthly transient, K frozen, and scores it on two blocks: ``nse_log`` on
the gauge, declared as a ``support = "point"`` output with ``observes``, next to
``distance_gap`` on the same network output. That second block is the one thing
the named protocol does not offer; writing the stages out is what makes room
for it.

Stage two gives the two blocks a share table, ``{ hydrograph = 0.8,
network_share = 0.2 }``, in :toml:`calibration.phases.objective_blocks` instead
of a weight on each block: this stage sets its own balance, normalised to sum to
one, without touching what another phase might read from the same blocks.
``network_share`` is the network gap with ``normalize_cost = true``, divided by
the output's :toml:`validity_length|calibration.outputs.<name>.validity_length`
(Eq. 4, ``"auto"`` = 2 h_obs), so both blocks are pure numbers and a share is a
share rather than an exchange rate between metres and an efficiency. Stage one
keeps the gap in metres, where its interval is read in mesh cells. Stage two
also names no :toml:`method|calibration.phases.method`: the hydrograph block is
not signed, so the phase has a cost to minimise and gets ``scipy_nelder_mead``
on its own; ``--list-phases`` prints the choice and why.

:toml:`calibration.phases.scoring_window` on stage two leaves the spin-up year
out of both blocks. The hydrograph keeps its months from that date on. The
network output reads one state, dated at the stamp that closes its period, the
last month here, and the window has to hold that stamp: ``hmp calibrate
--check`` refuses the file before any solve when it does not.
:toml:`time = "2003-08-15"|calibration.outputs.<name>.time` on the output would
read the state of August 2003 instead, the period that holds that date.

.. literalinclude:: recipes/calibration_staged_by_hand.toml
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

Run ``hmp calibrate --check`` on your copy before the first solve. It reports
every problem at once and solves nothing. :doc:`calibrate` lists its findings
with their real text.

One finding is a warning rather than a refusal, and the network recipes meet
it: an objective scored only on a network output that moves more than one
parameter, such as ``K`` and the aquifer thickness together. The two act on the
criterion only through their product :math:`T = K \cdot d`, so they form a
ridge in that cost and the search returns one point of the ridge, not an
identifiable pair. Freeze every parameter on that objective but one, or add an
output this search does not share the ridge on, such as the hydrograph.

Calibrate the aquifer thickness
-------------------------------

``hmp config targets project.toml`` lists what a project can calibrate, with
the name you write after ``[calibration.parameters.`` (see :doc:`calibrate`).
Add ``--json`` for the same list as machine-readable records.

The aquifer geometry itself is calibrable on the two scalar depth models, and
the list shows only the field the project's own
:toml:`domain.depth_model.kind` exposes, under its short name:

.. list-table::
   :header-rows: 1
   :widths: 30 30 20 20

   * - kind
     - name
     - space
     - prior
   * - ``constant_thickness``
     - :toml:`thickness|domain.depth_model.thickness`
     - log
     - ``log_uniform``
   * - ``flat_substratum``
     - :toml:`substratum_elevation|domain.depth_model.substratum_elevation`
     - linear
     - ``uniform``

The range the registry accepts for each is in the ``physical range`` column of
``hmp config targets``.

.. code-block:: toml

   [calibration.parameters.thickness]
   bounds = [5.0, 300.0]

``thickness`` is searched in log space because it enters :math:`T = K \cdot d`
as a factor, exactly like :math:`K`, and the sensitivity range of
:cite:`abherve2023` spans nearly two decades, 5 to 300 m.
``substratum_elevation`` is searched in linear space instead, because an
elevation can be negative and has no natural zero. Neither field defaults its
search bounds from the registry range: the range only guards a declared bound,
it is not a box to search blindly, so ``bounds`` is required in the file for
both, the same rule ``K`` already follows. The raster depth models,
``raster_substratum`` and ``raster_thickness``, are not searchable and list
nothing: their raster is a map of the site, not a scalar, so compare one run per
raster instead of calibrating one.

Moving the thickness changes :math:`T = K \cdot d` exactly as moving :math:`K`
does. On the stream-network criterion, searching :math:`K` alone at a fixed
thickness identifies :math:`T/R`, the quantity :doc:`calibrate-on-the-stream-network`
describes; searching the thickness alone at a fixed :math:`K` identifies the
same ratio from the other factor. Searching both together on that criterion
alone is equifinal, because the criterion only ever sees their product: it
takes another observation, such as the hydrograph, to separate them.

A thickness search re-runs the pipeline from ``setup_process`` for every
trial, because the domain the mesh is built on depends on the depth model; it
never rebuilds the mesh itself, so a raster or a grid change still needs a new
run rather than a calibration.

What the report says about the search
-------------------------------------

The interval beside each value, the search-bound flag and the pairs of
parameters that moved together are read in :doc:`calibration-uncertainty`. How
an engine stops and how ``max_iter = "auto"`` sizes a budget are in
:ref:`calibrate-stopping`. Two report entries say what the search itself
proved:

``extra["search"]``
   ``{converged, stopping_rule, max_iter, extension, n_evaluations}``, on
   every calibration, whichever engine ran.

``extra["bracket"]``
   ``{parameter, low, high, relative_width, closed}``, in physical units,
   once a bisection has found a sign change. It is what the search proved
   about the root, and it is distinct from ``parameter_intervals``, which
   reads a tolerance on the trials after the fact rather than the search's
   own bracket.

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
improves the number by changing the ruler. The mesh step also reads its
sections once from the raw file, not from the configuration of each trial, so
the value would never reach the mesh.

A mesh question is a convergence question, and it is answered by a sweep: one
run per mesh, compared, and read for convergence rather than for a best score.

.. code-block:: toml

   # not checked: a comparison file, not a project file
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

:doc:`compare-runs` explains the comparison file, its audit and its outputs.

A cell may be a whole calibration rather than a single run, which is what a
structural sweep actually is: one complete calibration per mesh, each with its own
plan. Declare it in the cell's overlay:

.. code-block:: toml

   # not checked: an overlay of a comparison cell, not a project file
   [comparison.simulation.overlay.workflow]
   mode = "calibration"

   [comparison.simulation.overlay.calibration]
   protocol = "matching_hydrographic_network"

The child is materialised the same way and dispatched by ``hmp run`` on its
own ``[workflow] mode``, so the cohort machinery does not need to know which kind of
cell it built. What it must not do is rank them: the criterion is normalised by
cell size, so the cheapest cost belongs to the finest mesh whatever the
hydrogeology.

Read the spread across the three as the numerical error on whatever you report,
and refine until it stops moving. Calibrate on the coarsest mesh whose answer no
longer changes: a finer one buys solve time, not information. Running the
calibration on each mesh in turn and keeping the K that scored best is the same
circularity in a longer form, because the criterion those K are compared on is
itself normalised by cell size.
