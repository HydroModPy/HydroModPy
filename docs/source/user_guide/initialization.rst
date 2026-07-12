Initialization and spin-up
==========================

.. note::

   Use this page when the question is: "what state does the transient run start
   from, and how do I keep the spin-up out of my calibration?"

A transient run needs a representative antecedent state: the value of every
variable that persists between stress periods at the start of the simulation.
For a flow model that is the hydraulic head field; when a lake is present it is
also the lake stage. A poor antecedent state biases the first part of the run,
where the model relaxes from the initial guess toward its real trajectory, and a
calibration that includes that relaxation absorbs it into the storage parameters.

HydroModPy builds the antecedent state with three cooperating controls, each
configurable and each safe to leave at its default.

Steady warm-up period
---------------------

``[flow] first_period_steady = true`` (the default) marks the first solver stress
period as steady state. Its solution seeds the transient periods that follow.

The steady period is forced with the **long-term mean recharge**, not the first
window's recharge. ``[flow.sinks_sources.recharge] first_clim = "mean"`` (the
default) makes period 0 use the record mean, and the recharge/EVT split assigns
every steady period the per-cell time mean of the recharge and of the routed
climatic deficit. Equilibrating to average conditions, rather than to one
arbitrary window, is the standard warm-up practice and keeps the calibrated
storage parameters unbiased.

Set ``first_clim = "first"`` to force the first window instead, or a numeric
value to force a fixed rate.

A single steady solve is cheap, but it cannot represent a seasonally varying
antecedent state and it says nothing about the lake stage. For a strongly
seasonal system, or a reservoir with a fluctuating pool, also exclude a burn-in
window from the objective (next section).

Burn-in excluded from calibration
---------------------------------

``[calibration] warmup_periods = N`` drops the first ``N`` periods of every
observed and simulated series before the objective metric is computed. The
window where the state still depends on the initial condition then does not
enter the calibration. The default is ``0`` (no exclusion).

Size ``warmup_periods`` by **initial-condition insensitivity**: increase it until
the objective stops changing. The correct length is the point past which the
metric no longer depends on how the run was started, not a fixed guess.

The exclusion is applied per output, so a multi-output objective block drops the
first ``N`` periods of each series independently.

Adaptive time stepping
----------------------

Weekly or longer stress periods solved in a single time step can carry a large
budget error, or fail to converge, on the periods where littoral cells wet and
dry under the Newton formulation. ``[modflow6.runtime] mf6_ats = true`` (opt-in,
off by default) enables MODFLOW 6 adaptive time stepping on the transient
periods: each period starts at its full length and MODFLOW 6 subdivides only the
periods it cannot solve in one step. Output is still written once per period, so
the extracted time axis is unchanged.

Initial heads
-------------

The initial head field is the model top everywhere. Under the Newton
formulation this affects convergence only, not the final result, and starting
wet is the robust choice for an unconfined model. There is no need to change it.

Choosing a strategy
-------------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Situation
     - Recommended setup
   * - Flow only, insensitive to the start
     - Steady warm-up (default); ``warmup_periods`` optional.
   * - Long chronicle, calibrated
     - Steady warm-up plus a ``warmup_periods`` sized by initial-condition
       insensitivity.
   * - Reservoir with a fluctuating pool
     - As above; enable ``mf6_ats`` if the littoral wet/dry periods stress the
       solve.

The steady warm-up handles the aquifer heads. A lake adds its stage to the state
that must equilibrate, and the burn-in window is what lets both settle before the
objective starts.

Advanced: restart and cyclic spin-up
------------------------------------

- **Restart (hotstart).** ``[flow] restart_from = "<prior-run>.zarr"`` reads the
  head field and the lake stage from a previous run's Zarr and uses them as the
  initial state, overriding ``[flow.ic]`` and each lake's ``stageinit``. The two
  runs must share the same mesh, so enable ``[mesh_catchment] cache = true``:
  the cache pins the grid between runs (the generator is not deterministic on
  its own), and a cell-count mismatch is refused rather than silently
  reindexed. A lake absent from the prior run keeps its ``stageinit``.
- **Cyclic spin-up to dynamic equilibrium.** ``hmp spinup <toml>`` repeats a
  representative window, restarting each cycle from the previous cycle's state,
  until the aquifer heads and the lake stage stop changing between cycles (L-inf
  below tolerance). This gives a seasonally consistent antecedent state that a
  single steady solve cannot, and it is the right method when the lake stage and
  the heads are strongly coupled. Configure it under ``[spinup]``:
  ``max_cycles``, ``tol_head`` / ``tol_stage`` (metres), and an optional shorter
  ``window_start`` / ``window_end`` so each cycle repeats a representative period
  rather than the full chronicle. The driver reuses one model, so the mesh is
  identical across cycles; it prints the converged Zarr path to set as
  ``[flow] restart_from`` on the production run (enable ``[mesh_catchment] cache``
  there so that run reproduces the mesh).

References
----------

- Anderson, M.P., Woessner, W.W., Hunt, R.J. (2015). *Applied Groundwater
  Modeling: Simulation of Flow and Advective Transport*, 2nd ed. Academic Press.
  ISBN 978-0-12-058103-0.
- Langevin, C.D., et al. (2017). *Documentation for the MODFLOW 6 Groundwater
  Flow Model*. USGS Techniques and Methods 6-A55.
  `doi:10.3133/tm6A55 <https://doi.org/10.3133/tm6A55>`__.
- Ajami, H., et al. (2014). Assessing the impact of model spin-up on surface
  water-groundwater interactions using an integrated hydrologic model. *Water
  Resources Research* 50(3), 2636-2656.
  `doi:10.1002/2013WR014258 <https://doi.org/10.1002/2013WR014258>`__.
- Seck, A., et al. (2015). Spin-up behavior and effects of initial conditions for
  an integrated hydrologic model. *Water Resources Research* 51(3), 2188-2210.
  `doi:10.1002/2014WR016371 <https://doi.org/10.1002/2014WR016371>`__.
