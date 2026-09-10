Three calibrations to start from
================================

Three complete configurations, shipped as files rather than as snippets, so
that a copy is a copy and not a transcription. Each one loads: a unit test
validates all three on every commit, which is what keeps them true after a key
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

.. _recipe-single-gauge:

One parameter, one gauge, one metric
------------------------------------

The shape almost every calibration starts from. A hydraulic conductivity is
swept over a bounded range and scored against one observed discharge series.

Two lines carry most of the modelling decision. ``bounds`` states what the site
could plausibly be, and a range far wider than the evidence buys a search over
a region the data already excludes. ``warmup_periods`` drops the head of the
record from the score, because that stretch is still forgetting the initial
condition; size it by raising it until the objective stops moving.

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
stages, their criteria, the regime and time-grid overrides that make the first
steady and the second transient, and the objective block wiring. What stays in
the file is what belongs to the site.

.. literalinclude:: ../recipes/calibration_matching_hydrographic_network.toml
   :language: toml

A file cannot both name a protocol and declare its own ``[[calibration.phases]]``
or ``[[calibration.objective_blocks]]``: that is two answers to one question,
and it is refused rather than silently resolved. Drop the protocol to write the
stages by hand, or drop the stages to let the protocol write them.

Every option under ``[calibration.protocol]`` has a default that reproduces the
published method, so the shortest form of this recipe is one line:

.. code-block:: toml

   [calibration]
   protocol = "matching_hydrographic_network"

The engines are not part of the method. ``steady_method`` and
``transient_method`` take any registered optimizer, so the same two criteria can
be walked by a bisection, by Nelder-Mead, or by Optuna without changing what is
being calibrated.

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
   flow.param.Ss.field.value             1e-05       m-1  1e-09 .. 0.001
   flow.param.Sy.field.value              0.05         -  0.0001 .. 0.5
   flow.sinks_sources.recharge.values         0    mm/day  -

The list comes from the resolved configuration, so it names the parameters and
boundaries this project actually declares, not everything the schema could hold.
The three columns are what a bound is written from: where the value sits today,
in what unit, and the range the physical registry will refuse outside of. A
range shown as ``-`` means the registry does not know this identifier, so
nothing will check the bounds for you.

Add ``--json`` for the same catalogue as machine-readable records.

Reading the value the search returns
------------------------------------

A calibration returns one number per parameter, and a number on its own says
nothing about its own standing. The report adds two things read off the trials
the search already ran, so they cost no extra model runs.

**How wide the optimum is.** ``parameter_intervals`` gives, per parameter, the
range of sampled values whose cost stayed within 5 % of the best, together with
how many trials that was out of how many. Read it as "the search could not tell
these apart", not as a confidence interval: it rests on no error model, and a
parameter the search never varied far has a narrow range because nothing else
was tried.

The flag to read first is whether the range runs into a search bound. There the
record did not determine the parameter, the search simply ran out of room, and
widening the bounds is the next step rather than reporting the edge as a result.
The run says so in one line:

.. code-block:: text

   K = 3.1e-06, and 14 of 60 trials scored within 0.081 of the best over
   [2.4e-06, 4.8e-06].
   Sy = 0.35, and 31 of 120 trials scored within 0.12 of the best over
   [0.19, 0.35]; that range runs into the upper search bound.

The width is a decision, so it is written in the file:

.. code-block:: toml

   [calibration.uncertainty]
   method = "cost_profile"
   mode = "relative"
   tolerance = 0.05

A criterion whose best cost is zero, such as the stream-network gap, has no
fraction of itself to take: five per cent of zero is zero and no interval comes
back. State the width in the unit of the cost there instead, and the run says so
when it has to:

.. code-block:: toml

   [calibration.uncertainty]
   mode = "absolute"
   tolerance = 25.0        # metres of network offset

**Whether two parameters were told apart.** ``correlated_parameters`` lists the
pairs that moved together across the whole search to hold the same cost. Such a
pair was not identified: the search stopped somewhere on a ridge and reported
that point as a minimum. The sign is kept, because it says which way the
trade-off ran.

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

   hmp compare mesh_sweep.toml

Read the spread across the three as the numerical error on whatever you report,
and refine until it stops moving. Calibrate on the coarsest mesh whose answer no
longer changes: a finer one buys solve time, not information. Running the
calibration on each mesh in turn and keeping the K that scored best is the same
circularity in a longer form, because the criterion those K are compared on is
itself normalised by cell size.
