Three calibrations to start from
================================

Three complete configurations, shipped as files rather than as snippets, so
that a copy is a copy and not a transcription. Each one loads: a unit test
validates all three on every commit, which is what keeps them true after a key
is renamed.

.. code-block:: bash

   hmp calibrate docs/source/user_guide/recipes/calibration_single_gauge.toml

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

A criterion whose best cost is zero, such as the stream-network gap, has no
fraction of itself to take. The intervals are then left out rather than computed
under a rule nobody chose; ask for them in cost units with
:func:`hydromodpy.calibration.optim.tolerance.tolerance_intervals` and
``mode="absolute"``.

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
run per mesh, compared. Use ``mode = "comparison"`` and read the spread of the
results as the numerical error of the answer, not as a score to minimise.
