How wide a calibrated value is
===============================

A calibration returns one number per parameter. Beside it, the report gives an
interval: the range of values the search tried that scored close enough to the
best to not be told apart from it. This page says what that interval is, the
three ways to obtain it, why the default width is what it is, and when to
write a different one.

What the interval is, and is not
---------------------------------

The interval never moves the calibrated value. It is read off the trials the
search already ran, after the fact, and it says one thing only: *these other
values, inside this range, scored almost as well as the best one*. Two
readings that follow from that:

- A narrow interval can mean the parameter is well constrained, or it can mean
  the search never tried far from the best. Nothing here tells the two apart;
  read :doc:`calibration-recipes` on the search bound flag for the check that
  does.
- It is **not a posterior distribution**. A posterior needs a likelihood, and a
  likelihood needs a criterion built from residuals with an error model on
  each observation. An efficiency score such as NSE, KGE or ``nse_log`` is an
  aggregate already stripped of its units, and a posterior computed from one
  would carry a precision nothing in the calculation established. Sampling a
  real posterior also costs thousands of model runs, not the handful the
  methods below cost.

``method = "posterior"`` is refused for that reason, with the same
explanation, on ``CalibUncertaintyDecl``
and on a phase's own ``uncertainty`` table.

The three methods
------------------

Written in ``[calibration.uncertainty] method`` or in a phase's own
``uncertainty.method``.

``cost_profile`` (the default)
   Reads the interval off the trials the search already produced: every
   sampled value whose cost stayed within the tolerance of the best. It costs
   no extra model run and rests on no error model, which is why it is the
   default. It cannot see a second, separate optimum: if the search only ever
   explored one basin, the interval describes that basin alone.

``multistart``
   Runs the whole search again, ``restarts`` times, from ``restarts``
   different starting points, and reports the spread of the optima reached.
   It is the only one of the three that can see a second basin, because each
   restart is free to land in a different one. It costs that many times the
   runs of one search: eight restarts of a hundred-evaluation phase is eight
   hundred model runs. The calibrated value itself does not move; it is the
   best of the restarts.

``linearized``
   Takes derivatives of the cost around the answer, one model run per
   parameter, instead of searching again. It is first-order: exact where the
   cost is linear about the optimum, approximate in proportion to how curved
   it really is, and, like the other two, not a posterior. From the same
   derivatives it reports, for each parameter, which other one it trades off
   against and by how much, as a signed correlation read off the covariance
   the derivatives build. That is sharper than the plain warning any method
   can trigger, that two parameters moved together across the trials and were
   never told apart (``correlated_parameters``, read off the trace and not
   from a derivative): ``linearized`` is the only one that quantifies the
   trade-off rather than only flagging it. The step the derivatives are taken
   with, ``perturbation``, is a fraction of each calibrated value (0.01 moves
   it by one per cent); too small and the difference is solver noise, too
   large and it is no longer a derivative, and the honest check is to move it
   and see whether the reported width moves too.

.. list-table::
   :header-rows: 1
   :widths: 18 30 30 22

   * - method
     - extra runs
     - sees
     - needs
   * - ``cost_profile``
     - none
     - one basin, off the trace already run
     - ``tolerance``, ``mode``
   * - ``multistart``
     - ``restarts`` full searches
     - a second basin, if a restart lands in one
     - ``restarts`` (at least 2)
   * - ``linearized``
     - one run per parameter
     - which parameters trade off against which
     - ``perturbation``

The default width, and why
----------------------------

Left unwritten, ``cost_profile`` reads a **tolerance** that follows what is
scored, by a rule with one exception:

- **A phase, or a whole calibration with no phases, scored only by network
  distances** (every one of its objective blocks reads ``distance_gap`` or
  ``distance_mean``): ``mode = "absolute"``, and the tolerance is **one mesh
  cell**, in metres. The cell is the median distance between the centres of
  neighbouring cells, measured by the network criterion on the mesh it
  scores. A stream cannot move by less than a cell, so two gaps closer than
  that are not something the search could tell apart in the first place.
- **Every other phase**: ``mode = "relative"``, and the tolerance is **five
  per cent of the best cost**. With an NSE of 0.80, the cost is 0.20 and the
  interval keeps the trials scoring NSE ≥ 0.79.

The exception exists because the two families of criteria do not share a
zero. A criterion solved at zero, such as the stream-network gap, has no
fraction of itself to take: five per cent of zero is zero, and a relative
tolerance on it would report no interval at all, on the criterion where a
physical floor (a mesh cell) is exactly what a reader wants instead.
``hmp calibrate --check`` refuses ``mode = "relative"`` on a phase scored only
by network distances, so the mismatch cannot slip through unnoticed.
``hmp calibrate --list-phases`` prints, for each phase, the width in use and
where it came from.

Overriding it
---------------

A section-level default, for every phase that does not say otherwise:

.. code-block:: toml

   [calibration.uncertainty]
   method = "cost_profile"
   mode = "relative"
   tolerance = 0.05

A per-phase override, key by key, over the section:

.. code-block:: toml

   [[calibration.phases]]
   name = "k_steady"
   parameters = ["K"]
   regime = "steady"
   objective_blocks = ["network"]
   uncertainty = { mode = "absolute", tolerance = 150 }   # two cells: a coarser map

A phase reads its own key when it is written, then the section's, then the
default above. ``restarts`` and ``perturbation`` belong to a method: a phase
that names a different ``method`` than the section does not inherit the
section's ``restarts`` or ``perturbation``, since those numbers were sized for
the section's method and mean nothing for another one.

When to change it
--------------------

Leave the default alone until one of these applies:

- **The mesh changes resolution.** The one-mesh-cell default is measured on
  the mesh a run actually solves on, so it already follows a refinement; no
  file needs editing for that alone. Write an explicit ``tolerance`` only when
  a coarser or finer agreement than one cell is wanted on purpose, for example
  ``150`` on a project whose cell is 75 m, to read two cells instead of one.
- **The default 5 % reads too wide, or too narrow, for the criterion at hand.**
  An efficiency near 1.0 leaves little room below it, so 5 % of a small cost
  can already reach the search bounds; a criterion with a wide plausible
  range may want a tighter fraction to say something.
- **A second optimum is suspected.** ``cost_profile`` cannot see one by
  construction; switch to ``multistart`` to find out, at the cost of running
  the whole search again several times.
- **The write-up needs to say which parameters compensate for which.** Only
  ``linearized`` reports that, from the same derivatives it uses for the
  width.

Whichever method produced a number, the report and ``hmp calibrate`` say so:
state the method beside the interval, the same way :doc:`stream-network-calibration`
asks a published conductivity to carry the ratio it rests on.
