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

Three things have to be true, and the first is the one people skip.

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

``stream_geometry_path`` is not optional. Without it the geographic pipeline
stops on ``geographic.enforce_streams.stream_geometry_path is unset.`` at the
first step, before anything is calibrated. A bare filename is looked up under
``<data>/hydrography/``, where ``<data>`` is the parent of the DEM family
directory.

A project declaring that path gets the agreement measured whether or not
``enabled`` is set, which is how you find out that the burning is needed. It
goes to ``stream_dem_agreement.json`` in the geographic directory, as
``alpha``: the ratio between the mapped network and its own downslope closure,
where one means the linework follows the talwegs and below 0.90 the run warns.
The calibration recomputes the same ratio on the solver mesh and publishes it
per trial as ``alpha_obs_closure``, warning on the same threshold. Redo the
burning at every change of resolution: the ratio between the width of the
linework and the cell size changes with it.

**The drain conductance must stay proportional to the conductivity.** Leave
``[flow.bc.cauchy.drainage] value`` at zero, or at anything not strictly
positive, so the fallback applies: ``C = K * cell_area / top_thickness`` on both
MODFLOW backends, ``C = K * cell_area`` on Boussinesq. That proportionality is
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

Declaring the two stages
------------------------

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
   bounds    = [1e-9, 1e-3]
   transform = "log"
   path      = "flow.param.K.field.value"
   units     = "m/s"

   [calibration.parameters.Sy]
   bounds    = [1e-3, 3e-1]
   transform = "log"
   path      = "flow.param.Sy.field.value"

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
   name              = "steady_k_over_r"
   description       = "Zero of the signed gap D_so - D_os, by bisection on K."
   method            = "bisection"
   max_iter          = 18
   parameters        = ["K"]
   objective_blocks  = ["abherve_gap"]
   freeze_on_success = true

   [calibration.phases.optimizer_kwargs]
   rel_tol      = 0.01
   sweep_points = 7

   [[calibration.phases]]
   name       = "transient_sy"
   method     = "grid"
   max_iter   = 9
   parallel   = 4
   parameters = ["Sy"]
   variable   = "discharge"
   objective  = "nse_log"
   depends_on = "steady_k_over_r"

   [calibration.phases.scoring_window]
   start = "2012-01-01"
   end   = "2015-12-31"

Declaring the ``[[calibration.phases]]`` table is what switches the runner to
staged mode. Without it nothing changes for an existing configuration.

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

``weighting = "area"``
   Recommended as soon as the mesh is refined along the streams, which is the
   usual refinement: an unweighted mean over-samples the river corridor, where
   distances are smallest. Both weightings are always reported, and their gap
   measures that effect directly.

``tau_specific_ratio``
   A cell releasing less than this fraction of its own recharge is not a
   stream. Specific and not absolute, so the mask follows the physics and not
   the mesh refinement. Zero reproduces the criterion of the paper, which gives
   no threshold at all.

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
   $ hmp calibrate calibration.toml --phase steady_k_over_r

The first form is the one to use. It runs the phases in declaration order and
is the only form that produces the two-stage result the page describes.

``--list-phases`` prints the declared phases and exits without running
anything.

``--phase`` selects a single phase, and it only accepts one that does not
depend on another. On the configuration above that means ``steady_k_over_r``,
and nothing else: ``--phase transient_sy`` is refused, because
``transient_sy`` declares ``depends_on = "steady_k_over_r"`` and a phase whose
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
   rather than returning the better of the two. A failed evaluation at an end
   skips the widening: the surface is the problem, not the interval.

``roptim`` and ``roptim_valid``
   The validity indicator of Equation 4, against the ``roptim_max`` bound (two
   by default). It **qualifies** the result and does not withhold it: a
   violation warns and the value comes back, unless you set
   ``on_roptim_violation = "error"``, which raises instead. And it measures
   agreement, not correctness, so do not read it as a quality score of the
   model.

``R_mean_m_s``
   The denominator of the calibrated ratio. It is what makes the result a
   ``K/R`` rather than a ``K``, and comparing it across the trials of a session
   is how you check the first stage really held the recharge still.

``alpha_obs_closure`` and ``frac_reachable_obs_raw``
   The two numbers that say whether the pre-treatment was done and whether it
   was enough. They describe the geometry, not the trial, so they are identical
   across a session: the static geometry is rebuilt at every trial from the
   same topography and comes out the same.

``frac_unreachable_so`` and ``frac_unreachable_os``
   The share of each support whose descent ends without meeting its target.
   Beyond ``max_unreachable_fraction`` (five per cent by default) the trial
   fails loudly, because averaging over a truncated support is a fiction and
   the cells dropped are never a random sample: they sit upstream of a pit.

``D_so_median``, ``D_so_p90``, ``D_so_top5_share``
   The shape of the tail, with ``D_os_median``, ``D_os_p90`` and
   ``D_os_top5_share`` beside them for the other support. The median is usually
   zero and a few long branches carry most of the value, so the mean is not a
   typical gap.

``n_valid``, ``n_excess``, ``n_missing``
   The three-class counts. The criterion balances the last two against each
   other, which is what the confusion map draws.

What to publish
---------------

Publish the ratio, not the conductivity. That advice stands, and it is work you
have to do yourself: the calibration returns the calibrated conductivity raw, in
``best_parameters`` of the report, and it publishes no ratio at all. There is no
``t_over_r``, no ``k_over_r`` and no ``k_optim`` anywhere in the output. Divide
by ``R_mean_m_s``, which every trial publishes, and state the recharge series it
came from beside the number: the conductivity inherits it entirely, and changing
reanalysis moves it by up to a quarter.

What the code does publish, and what belongs in the paper beside the value, is
the diagnostic set above: ``D_so`` and ``D_os``, the cost ``J`` with its signed
form ``J_signed``, ``Doptim`` and ``roptim`` with ``roptim_valid``. See the
section on known biases of the theory page before reusing any of them.
