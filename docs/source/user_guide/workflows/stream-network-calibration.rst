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
   mode = "constant"
   depth_m = 30

Every run reports ``alpha_obs_closure``, the ratio between the mapped network
and its own downslope closure. One means the linework follows the talwegs.
Below 0.90 the run warns, and the value it produces reads a dataset
disagreement rather than hydrogeology. Redo the burning at every change of
resolution: the ratio between the width of the linework and the cell size
changes with it.

**The drain conductance must stay proportional to the conductivity.** Leave
``[flow.bc.cauchy.drainage] value`` at zero so the proportional fallback
applies. That proportionality is what makes the ratio the calibrated quantity;
a fixed conductance breaks the invariance from a factor 1.05 onwards.

**The recharge must be frozen during the first stage.** The criterion at one
per cent is on the ratio, which equals one per cent on the conductivity only
when the recharge does not move. Every trial records the mean recharge it ran
with, so a violation is visible.

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
   zero and may never get small.

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

``scoring_window`` rather than ``warmup_periods``
   A window in dates means the same span whatever the output frequency; a count
   of samples does not. The two are mutually exclusive and declaring both is
   refused.

Running it
----------

.. code-block:: console

   $ hmp calibrate calibration.toml
   $ hmp calibrate calibration.toml --list-phases
   $ hmp calibrate calibration.toml --phase transient_sy

Reading the output
------------------

Every trial writes about thirty diagnostics into ``trials.jsonl`` and into the
iteration table, with no run promoted. The ones to look at first:

``J_signed``
   The signed residual. Its sign says which side of the balance the trial is
   on, and it is what the search brackets. If it never changes sign over the
   sweep, the search stops and says so rather than returning the better end.

``roptim`` and ``roptim_valid``
   The validity indicator of Equation 4. It **qualifies** the result and never
   withholds it: a calibration is asked for a number. And it measures
   agreement, not correctness, so do not read it as a quality score of the
   model.

``alpha_obs_closure`` and ``frac_reachable_obs_raw``
   The two numbers that say whether the pre-treatment was done and whether it
   was enough. They describe the data, not the trial, so they are identical
   across a session.

``frac_unreachable_so`` and ``frac_unreachable_os``
   The share of each support whose descent ends without meeting its target.
   Beyond the declared bound the trial fails loudly, because averaging over a
   truncated support is a fiction and the cells dropped are never a random
   sample: they sit upstream of a pit.

``D_so_median``, ``D_so_p90``, ``D_so_top5_share``
   The shape of the tail. The median is usually zero and a few long branches
   carry most of the value, so the mean is not a typical gap.

``n_valid``, ``n_excess``, ``n_missing``
   The three-class counts. The criterion balances the last two against each
   other, which is what the confusion map draws.

What to publish
---------------

``t_over_r`` first, ``k_over_r`` second, and ``k_optim`` last with the recharge
series it was computed from. The conductivity inherits that series entirely:
changing reanalysis moves it by up to a quarter. See the section on known
biases of the theory page before reusing any of the three.
