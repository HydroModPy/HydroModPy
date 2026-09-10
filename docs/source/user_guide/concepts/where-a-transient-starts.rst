Where a transient starts
========================

A transient run has to be told what the aquifer held before the first time step.
Nothing about that state is in the forcing, so it is a modelling choice, and it
is one the result keeps: too full an aquifer drains through the first months and
the hydrograph carries a recession nobody put there; too empty and the streams
appear late.

HydroModPy offers four ways to say it. They differ in what they assume and in
what they cost, not in quality: the right one depends on what the site gives
you. Every field named below is documented in
:doc:`../config_reference/flow`, and the calibration keys in
:doc:`../config_reference/calibration`.

Equilibrium under the mean of the record
----------------------------------------

The default, and the one to reach for when nothing points elsewhere. The model
is solved once in steady state under the time mean of the recharge chronicle,
and the transient starts from those heads.

.. code-block:: toml

   [flow.ic]
   type = "steady_state"

It says: before the record, this catchment sat at the equilibrium its own
average forcing implies. That is a reasonable statement for a headwater aquifer
under a stationary climate, it needs no data you do not already have, and it
costs one extra steady solve. It is what the criterion of the two-stage
stream-network method assumes, so a calibration that uses that method gets it for
free.

What it assumes is the part to check: that the mean of *your window* is a fair
stand-in for the decades before it. A record that starts inside a drought does
not average to the state that preceded it.

Equilibrium under a rate you state
-----------------------------------

The same steady solve, held at one rate you choose rather than at the mean of
the record.

.. code-block:: toml

   [flow.ic]
   type = "steady_state"
   source = "prescribed"
   rate = "500 mm/yr"

Use it when the antecedent conditions are known to differ from the record: a
pre-development baseline, a design rate a regulation names, a scenario whose
start is defined by a recharge and not by a date, or a long-term normal drawn
from a longer series than the one being simulated. It is also how two runs are
made to start from the *same* state when their windows differ, which is what a
scenario comparison needs.

The rate carries its unit: ``"500 mm/yr"``, ``"2 mm/day"``, or a bare number in
metres per second.

A level you write
-----------------

.. code-block:: toml

   [flow.ic]
   type = "top_offset"
   value = "2 m"

``top`` fills the aquifer to the surface, ``bottom`` empties it, ``top_offset``
sets the water table a stated depth below the surface, and ``custom`` sets one
elevation everywhere. These are guesses, not states the model produced, so a
transient that starts from one spends its first months forgetting it.

They earn their place in two situations: as the initial guess of the auxiliary
steady solve itself (which is what ``steady_state`` uses internally), and as a
deliberately crude start followed by a burn-in long enough that the choice
stops mattering. If you use one, exclude that burn-in from any calibration
score with ``[calibration] warmup_periods`` or ``scoring_window``, and size it
by raising it until the objective stops moving.

A state a previous run reached
-------------------------------

.. code-block:: toml

   [flow]
   restart_from = "runs/spinup_3/fields.zarr"

The heads (and each lake stage) of a prior run's last time step seed this one.
The two runs must share the mesh, cell for cell, so a gmsh grid needs
``[mesh_catchment] cache = true``; a shape mismatch is refused rather than
reindexed. Only a backend that declares it reads this key accepts it, so it is
never silently dropped.

Where the prior run comes from is the useful part. ``hmp spinup`` repeats a
representative window, restarting each cycle from the previous one, until the
heads and the lake stages stop moving between cycles:

.. code-block:: toml

   [spinup]
   window_start = "2010-01-01"
   window_end = "2012-12-31"
   max_cycles = 10
   tol_head = 0.01
   tol_stage = 0.01

.. code-block:: bash

   hmp spinup project.toml

This is the answer when the system has memory a single steady solve cannot
carry: a deep aquifer whose response time is years, a lake whose storage
integrates several seasons, or a model where the steady solve and the transient
do not see the same physics. It costs one run per cycle, which is why it is not
the default.

Read the result before using it. A loop that ran out of cycles still hands back
its last state, and the run says so: only a converged loop tags its last cycle
``spinup-converged``, and chaining a production run from a state that did not
settle is reported rather than assumed.

Choosing
--------

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Situation
     - Use
     - Because
   * - Nothing points elsewhere
     - ``steady_state``
     - One extra solve, no extra data, and a statement you can defend.
   * - Antecedent conditions differ from the record
     - ``steady_state`` with ``source = "prescribed"``
     - The state is set by a rate you name, not by the window you happen to run.
   * - Two runs must start from the same state
     - ``steady_state`` with ``source = "prescribed"``
     - Their windows differ, so their means differ, and their starts would too.
   * - The system's memory is longer than one steady solve carries
     - ``hmp spinup`` then ``restart_from``
     - Cycling reaches the state the forcing actually produces.
   * - The same antecedent is reused by many runs
     - ``restart_from``
     - It is computed once and read from disk after that.
   * - A long burn-in is affordable and will be excluded from the score
     - ``top`` / ``top_offset``
     - Simplest to state, and the burn-in absorbs the error.

The two-stage stream-network calibration assumes the first of these; see
:doc:`../workflows/stream-network-calibration`.

Whichever you pick, the honest check is the same: change it, run again, and see
whether what you report moves. If it does, the initial condition is part of your
result and belongs in the write-up next to the parameters.
