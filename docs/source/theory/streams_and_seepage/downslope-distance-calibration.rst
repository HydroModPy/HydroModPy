Downslope-distance calibration of the stream network
====================================================

This page explains the criterion that calibrates a catchment against the
spatial extent of its stream network rather than against a gauge
:cite:`abherve2023`, and how to read what it returns. It has a companion in
:doc:`network-metrics-and-extreme-k-sweep`, which covers the overlap metrics
that answer a different question.

Read it before running the method, and read the section on known biases before
reusing a number it produced. Two sections are prerequisites rather than
commentary: the surface the distances are measured on, and what the method
needs from the flow model. Both are enforced, because both had been silently
violated on a real catchment and both returned a plausible number while doing
it.

What it does, and why it is worth the trouble
---------------------------------------------

Most calibration needs a discharge series. This one needs a hydrographic
network, which is free, dense and available almost everywhere, and it needs no
gauging station at all. That is its value, and none of the caveats below
removes it.

The idea is that the extent of the stream network is itself an observation of
the aquifer. A conductive aquifer drains fast, the water table stays low, few
cells reach the surface and the network is short. A tight aquifer keeps the
water table high, seepage appears far upslope, and the network is long. So the
length of the simulated network is a reading of the ratio between what the
aquifer can transmit and what it receives.

The downslope topographic distance
----------------------------------

Let :math:`r` be the steepest-descent receiver graph over the mesh, so each
active cell has exactly one receiver, and let :math:`\ell(c)` be the distance
from a cell to its receiver, measured centre to centre. For a target set
:math:`T`:

.. math::

   d_T(c) =
   \begin{cases}
     0 & c \in T \\
     \ell(c) + d_T(r(c)) & c \notin T,\; r(c) \neq \varnothing \\
     +\infty & c \notin T,\; r(c) = \varnothing
   \end{cases}

Three things follow, and each one rules out an implementation that looks
reasonable.

There is no shortest path to look for. In single-flow-direction routing exactly
one descending path leaves a cell, so "the nearest downslope path" names the
only one there is. Any implementation reaching for a Dijkstra has misread the
definition.

It is not a Euclidean nearest distance. A seepage cell fifty metres from a
stream but on the far side of a divide is fifty metres away in the plane and
kilometres away downslope, because its water leaves into the other valley. A
criterion built on a planar nearest-neighbour tree measures something else.

It is not symmetric, and the asymmetry is the mechanism. :math:`d(a,b)` and
:math:`d(b,a)` differ; with a symmetric kernel the two averages below would
become two means of the same kernel over two supports, and their difference
would measure nothing but a difference of support.

The surface the distances are measured on
-----------------------------------------

A downslope distance is a length along a flow path, and a flow path only exists
once the depressions are resolved. On a raw surface the descent stops in a pit
that has no hydrological existence, and every cell behind that pit has no
distance at all: it enters the average as an unreachable cell rather than as a
length.

**The conditioning has to happen on the graph the distances are measured on.**
A raster conditioned before delineation is pit-free on its own grid and under
its own neighbourhood only. Read at mesh centroids it grows new pits, and it
drops the cells whose centroid falls on nodata. That route was measured on the
Nancon and left 51.9 per cent of the simulated support unreachable. The
criterion therefore floods the mesh itself, by the priority flood of Barnes,
Lehman and Mulla (2014) written over an explicit neighbour list instead of over
a raster, so that it applies to cells of any arity
(``hydromodpy/core/depression_filling.py``). Water is walked inwards from the
outlet through the lowest reachable rim, anything below that rim is raised onto
it, and one millimetre is added per step so the filled floor drains instead of
lying flat, which a steepest-descent graph needs in order to leave it at all.

Two objects have to be shared with the metric or the flood repairs nothing.
The neighbour graph is the first: fed the eight-neighbour graph while the
metric descends the four-neighbour one, every filled cell spills over a
diagonal the metric cannot take, and 99.8 per cent of the catchment stops
reaching the outlet instead of none of it. The outlet is the second: the flood
only guarantees a path to the cell it was seeded on, so the criterion seals
that same cell into the target rather than resolving an outlet of its own
afterwards.

Measured on the Nancon, a 60 395-cell MODFLOW-NWT mesh at 50 m: **17 166 cells
raised, by up to 48.7 m**; the unreachable share of the simulated support fell
from **13.6 per cent to 0.0**; and the outlet moved from an internal depression
at 130.3 m to the true low point of the catchment at 106.4 m.

The two mean distances and the criterion
----------------------------------------

Write :math:`S` for the simulated stream network and :math:`O` for the mapped
one. The criterion is

.. math::

   D_{so} &= \langle d_O(c) \rangle_{c \in S} \\
   D_{os} &= \langle d_S(c) \rangle_{c \in O} \\
   J &= \lvert D_{so} - D_{os} \rvert \\
   D_{optim} &= \tfrac{1}{2}\,(D_{so} + D_{os}) \\
   r_{optim} &= D_{optim} / L_{ref}

:math:`D_{so}` large means a network spilling far outside the mapped one, an
excess. :math:`D_{os}` large means one that never grew, a deficit. The
calibrated point is where they balance.

The criterion is not the diagnostic
-----------------------------------

This is the single point where a hurried reader goes wrong, so it is worth
stating twice.

**The cost is** :math:`J`, **and its zero is an intersection.** The two curves
:math:`D_{so}(K/R)` and :math:`D_{os}(K/R)` cross; the crossing is the answer.

:math:`D_{optim}` is large at both ends of the sweep, so it does have an
interior minimum, and minimising it is therefore a tempting substitute. It is
a different estimator. Nothing places its minimum at the crossing, and a
working implementation that made that substitution calibrated a different
quantity for years without anything saying so.

Both are needed, and they are not interchangeable. Inside one model structure,
:math:`J` finds the parameter and :math:`D_{optim}` cannot separate two points
that both balance. Between structures already balanced at :math:`J = 0`, only
:math:`D_{optim}` separates them. HydroModPy names them distinctly,
``distance_gap`` and ``distance_mean``, precisely so that the substitution
cannot be made by accident.

What counts as a seepage cell
-----------------------------

The simulated network starts from a mask: the cells where the aquifer returns
water to the surface. That mask is a strict test on the **release flux**, never
a test on :math:`h \geq z_{top}`. The flux is anchored by the mass balance and
the geometric reading is not; over eight decades of drain conductance the
median cell flux holds to three decimals while the geometric mask loses most of
its cells.

Under that test sits a threshold :math:`\tau`, there to reject what a boundary
package leaves on a cell that is dry for every practical purpose. What
:math:`\tau` is read against decides whether it is a floor or a second
calibration knob, and **that reference is an open question of the method**. Two
answers have been written and measured on the same catchment. They miss in
opposite directions, the shipped one is the inert one, and what follows reports
both rather than announcing a winner the method does not have.

**What the code applies is a share of the cell's own recharge**, :math:`\tau(c)
= \tau_{ratio} \cdot R \cdot a(c)`, with :math:`a(c)` the area of that cell and
:math:`R` the mean recharge of the built model. It is one number per cell.
Reading: a cell releasing less than :math:`\tau_{ratio}` of the water that falls
on it is not a source. The ratio is declared as ``tau_specific_ratio``, its
default is :math:`10^{-4}`, and zero removes the threshold entirely, which is
the purely geometric criterion of the paper.

**That reference is frozen over the search**, which the method requires: a
threshold moving with the trial would cost :math:`D_{so}(K/R)` its monotonicity
and the root search its meaning. Cell areas are static geometry and :math:`R` is
a property of the forcing, so :math:`\tau` moves only if the recharge does, and
that is checked rather than assumed: every trial publishes ``R_mean_m_s``, read
back from the built model, and a move between two builds warns and names both
values.

**What the threshold excluded is not measured.** The surviving cells INSIDE THE
SCORED CATCHMENT are counted per trial as ``n_seepage``, so the water bodies and
the out-of-catchment cells are already gone from that count; no diagnostic
carries the share of released water
:math:`\tau` rejected. Comparing ``n_seepage`` against a run at
:math:`\tau_{ratio} = 0` is the only reading of what a declared ratio cost.

**As defined it excludes nothing, and that is measured.** A cell does not
release the recharge that fell on it. It releases the drainage it collects from
everything upslope, a hundred to a thousand times its own recharge, so a small
fraction of that recharge sits far below anything the model produces. On the
Nancon at the calibrated conductivity, over the 380 cells releasing inside the catchment, **not one had a
flux below the default threshold**, and raising :math:`\tau_{ratio}` to 100
still kept 28. The default :math:`\tau` is :math:`3.5 \times 10^{-9}` m3/s on a
50 m cell there, three decades below the smallest release the model produces, and
nothing is excluded until :math:`\tau_{ratio}` passes 0.2. A knob documented as
a small fraction whose usable band starts near one is not a filter with a
conservative default, it is an inert declaration.

There is also nothing for it to clear on that run. Its DRN cells release either
exactly zero (59 640 of 60 395) or more than :math:`1.9 \times 10^{-6}` m3/s:
there is no population of near-zero releases between the two. A package that
does dribble, which DRN here does not, is the case the floor is held in reserve
for.

**And the reference carries the mesh.** The argument for a specific threshold is
that a fixed m3/s cut is nine times harsher on a cell three times smaller, which
assumes the release is a surface flux that converges under refinement. It is
not: :math:`q / (R\,a)` is a concentration factor with the discretisation in its
denominator. Aggregating one solved field of the Nancon from 50 m to 400 m
cells:

.. list-table::
   :header-rows: 1
   :widths: 14 16 22 24 24

   * - cell side
     - seepage cells
     - median :math:`q / (R\,a)`
     - water kept at 100 times the cell's own recharge
     - water kept at :math:`4.5 \times 10^{-4}` of what the model receives
   * - 50 m
     - 380
     - 49.6
     - 0.51
     - 0.94
   * - 100 m
     - 230
     - 19.9
     - 0.18
     - 0.97
   * - 200 m
     - 138
     - 7.7
     - 0.00
     - 0.99
   * - 400 m
     - 76
     - 4.1
     - 0.00
     - 0.996

A converged surface flux would hold the third column constant. It falls by a
factor 12, so a threshold read against it selects whatever the discretisation
gives it: the same declared value keeps half the released water at 50 m and
nothing at all at 200 m, while the same declared share of what the whole model
receives stays within six points of itself over a factor eight in cell size.
That last column is what motivated the other answer.

The other answer, written, measured and reverted
------------------------------------------------

Thresholding what the model receives instead, :math:`\tau = \tau_{ratio} \cdot
R \cdot A` with :math:`A` the area the mesh covers, is one number for the whole
mesh and does not move under refinement. It also holds still over the search on
its own: a steady model whose only sink is seepage returns every drop it
receives, so :math:`R \cdot A` is the total release at every trial, measured on
the Nancon at 2.1018 m3/s of recharge against 2.1025 of drain outflow,
unchanged from :math:`K = 10^{-7}` to :math:`10^{-3}`.

**It was implemented, swept, and rolled back the same evening. The code at HEAD
does not carry it**, and neither does the per-trial rejected-share warning that
shipped with it: a reader who remembers that instrument will not find it among
the diagnostics.

It fails on the property the root search rests on. At :math:`\tau_{ratio} =
10^{-4}` the cut lands at :math:`4.9 \times 10^{-4}` m3/s, above the many small
releases a low conductivity spreads over the catchment and below the few large
ones a high conductivity concentrates. The simulated network then **grows** with
the conductivity instead of retracting: on the Nancon variant with the reaches
in SFR the residual lost its monotonicity, running :math:`-270`, :math:`-7`,
:math:`+46`, :math:`+929`, :math:`+87`, :math:`+40` over the sweep, and the root
left for :math:`2.8 \times 10^{-8}`, three decades under the expected value.

Swept on the drain-only variant, where the direction of variation survives, the
same threshold shows where it stops filtering and starts calibrating. On the
Nancon, 60 395 cells at 50 m, 380 of them releasing inside the catchment, and
:math:`R \cdot A = 2.1` m3/s so that the second column is that product times the
ratio:

.. list-table::
   :header-rows: 1
   :widths: 14 20 18 22 26

   * - :math:`\tau_{ratio}`
     - :math:`\tau` (m3/s)
     - seepage cells
     - released water rejected
     - shift in the calibrated :math:`K`
   * - 0
     - 0
     - 380
     - 0 %
     - reference
   * - :math:`10^{-6}`
     - 2.1e-6
     - 380
     - 0.000 %
     - 0.0 %
   * - :math:`10^{-5}`
     - 2.1e-5
     - 377
     - 0.002 %
     - +0.9 %
   * - :math:`3 \times 10^{-5}`
     - 6.3e-5
     - 372
     - 0.013 %
     - +1.3 %
   * - :math:`10^{-4}`
     - 2.1e-4
     - 349
     - 0.23 %
     - +0.8 %
   * - :math:`3 \times 10^{-4}`
     - 6.3e-4
     - 310
     - 1.96 %
     - +14 %
   * - :math:`10^{-3}`
     - 2.1e-3
     - 155
     - 19.2 %
     - +29 %
   * - :math:`3 \times 10^{-3}`
     - 6.3e-3
     - 22
     - 67.4 %
     - +188 %

The last column is not a re-run bisection. Only the residual was recomputed, at
the one conductivity the search had already closed on, and converted through
the local slope of the residual, :math:`-598` m per decade of :math:`K`, the
secant between the two bracketing trials of that session. Read it as an order
of magnitude and not as a calibrated value: the secants of the tighter
bracketing pairs are half again as steep, near :math:`-970`, which would put
the :math:`3 \times 10^{-4}` row nearer eight per cent than fourteen, and the
last row is an extrapolation far outside any range where one slope holds.

The criterion is a staircase in the parameter, so the three figures under one
per cent say one thing and not three: nothing moved. What moved is the last
three rows, by an amount of the same order as the eleven per cent that
separates two solvers on this same catchment. **Past about two per cent of the
released water, the threshold is no longer filtering the sources, it is
shortening the network.** Shortening the network is exactly what the calibrated
ratio is there to do, so the two knobs then pull against each other and the
calibrated value becomes conditional on a number nobody tuned.

What the threshold should be a fraction of
------------------------------------------

Open. Neither reference is right, and the two miss in opposite ways. The cell's
own recharge is two orders of magnitude below the flux a releasing cell carries,
so it never selects anything. What the whole model receives is a single number
facing a population that spans decades, so it selects the wrong tail and inverts
the response of the criterion to its own parameter, which is the one property
the root search cannot do without.

One scale has not been tried: what the upslope contributing area of a cell
delivers to it, the accumulation, which is the only quantity that follows the
flux that cell actually carries. The accumulation itself is already computed on
the graph the criterion routes on, at every trial, to place the outlet and to
close the seepage pattern downslope; what does not exist is anything reading a
threshold against it, and nothing here claims that would work.

Until the question is settled, leave :math:`\tau_{ratio}` at its default and
read the simulated network as the unthresholded one, because on every run
measured so far that is what it is. A run whose release package really does
dribble needs this answered before its network means anything.

Which cells enter which average
-------------------------------

The two supports are treated differently, and this is a definition rather than
a convenience.

**The model does not produce a network, it produces sources.** A seepage cell
is a point where water appears, not a reach. The object comparable to a mapped
stream network is what those sources generate downslope, so :math:`S` is the
downslope closure of the seepage pattern, traced to the outlet.

**The mapped network is already a network**, so nothing is generated from it:
:math:`O` is taken raw. Closing it too would build observation out of the DEM,
which contradicts the premise that the network is independent of the DEM, and
it would erase the signal the validity bound exists to detect. On a network
displaced by a single cell, the closed reading returns :math:`r_{optim} = 0.87`
and accepts; the correct reading returns :math:`9.44` and rejects.

**One cell is added to the target of** :math:`D_{so}`: the outlet. If the
mapped linework stops short of it, the distance is infinite downstream of the
last reach, and since the simulated network retreats towards exactly that reach
as the ratio grows, the criterion loses its sign change at the high end of the
bracket and there is no root left to close. That cell is the low point of the
catchment the geographic step closed on the declared gauge, and it is the cell
the flood was seeded on, so writing that it belongs to the stream network is
true by definition rather than a fudge.

**Both supports are intersected with the catchment the geographic step
delineated.** Re-deriving one instead, by descending the model top to its own
largest basin, fails for the reason given in the section above: the model top
is never conditioned, so that descent ends in whichever internal depression is
biggest. Measured on the Nancon, the re-derived catchment held 1 368 cells of
the 60 395 in the mesh and **not one cell of the mapped network**, so every
trial refused; the delineated catchment holds 26 907 cells and 1 119 of the
mapped network. A run reaching the criterion without a delineated catchment
falls back to the re-derived one and says so with a warning: a synthetic domain
legitimately has no watershed, while a real run that lost one would otherwise
produce a plausible number from the wrong support.

The intersection itself is not a detail either. On a buffered model domain, ten
to fifteen per cent of the cells drain outside the basin and never meet the
mapped network; on the catchment alone the figure falls to a fraction of a per
cent. Measured on one real mesh: 14.9 per cent against 0.11 per cent. The
catchment is also what restricts the supports, never the solver's active
domain: cutting the graph on the model domain breaks the catchment into pieces
the flood cannot cross, and the descent then stops at a domain boundary instead
of at a stream.

**Water bodies stay in the graph and in the target, and leave both supports.**
A hillslope cell upstream of a reservoir has to be able to descend through it,
and open water must absorb a path that reaches it, but a line of hydrography
drawn across a reservoir is not the observation of a stream. Keeping lake cells
in the support of :math:`D_{so}` would inject one zero per lake cell and move
the root with the size of the reservoir.

The unreachable fraction, and the one direction its bound guards
----------------------------------------------------------------

A cell whose descent never meets the target has no finite distance. The
criterion never drops such a cell in silence: it saturates at :math:`L_{cap}`,
the longest descent to the outlet inside the catchment, computed once on the
static geometry and published per trial as ``L_cap``. Counting :math:`+\infty`
instead would make the mean infinite; censoring the cell instead would move the
support with the parameter, which is a moving denominator.

The fractions are counted on both sides and reported as
``frac_unreachable_so`` and ``frac_unreachable_os``. **The bound**
``max_unreachable_fraction`` **guards one of them, and only one.**

It guards :math:`D_{so}`, whose target is the mapped network with the outlet
sealed in. That target is static: it does not move from trial to trial, and on
a conditioned catchment every cell reaches it. Anything past a few per cent
there means the surface is not conditioned, and the mean would be a fiction
built on the saturation value. This is the direction the 0.03 to 2.5 per cent
of the reference measurement belongs to.

It does not guard :math:`D_{os}`, and must not. That target is the *simulated*
network, which is exactly what the calibration moves: at a high conductivity
the simulated network retracts into the talwegs and the mapped cells
legitimately have nothing left to descend into. At the high end of one Nancon
sweep, **81.4 per cent** of the mapped support was unreachable. That is the
measurement working, not failing, and it is the signal the root search reads to
close its bracket from above.

Weighting, and the reference length
-----------------------------------

The paper averages one pixel one vote, which on a regular grid is the same as
weighting by area. It stops being the same as soon as the mesh is refined along
the streams, which is the usual refinement: cell density is then highest
exactly where distances are smallest, so an unweighted mean over-samples the
river corridor. HydroModPy reports both weightings at every trial, as
``D_so_cell`` and ``D_so_area`` beside ``D_os_cell`` and ``D_os_area``, and
their gap measures the effect of the refinement directly. Which pair enters the
criterion is what ``weighting`` selects, one cell one vote by default.

:math:`L_{ref}` is the square root of the **median** cell area over the
catchment, not the mean. On a mesh refined along the streams a handful of large
buffer cells inflate the mean, and for a size ratio of three the two
conventions differ enough to move :math:`r_{optim}` across its bound. Declaring
``observed_position_accuracy`` raises :math:`L_{ref}` to that accuracy when it
is the larger of the two, because a finer mesh otherwise divides the
denominator without improving the agreement. That is not a hypothetical: the
known biases below carry a measured case of :math:`r_{optim}` halving on a
coarser grid with nothing else changed.

The validity bound and what it does not mean
--------------------------------------------

Equation 4 of the paper reads :math:`r_{optim} \leq 2`. HydroModPy computes it
against ``roptim_max``, reports it as ``roptim`` and ``roptim_valid``, and
**does not let it withhold the calibrated value**: a violation logs a warning
and the value comes back. A calibration is asked for a number; a coarse
agreement qualifies that number, it does not replace it with nothing. Setting
``on_roptim_violation = "error"`` turns that warning into a raise, which is an
explicit choice to be handed nothing rather than a qualified value.

Why the criterion has a root, and why the search brackets it
-------------------------------------------------------------

Three measured facts shape the search, and each is a line of the implementation.

**The residual is a step function.** The masks are discrete, so the two
averages jump when a cell switches, and the residual steps over zero rather
than reaching it. On one real catchment :math:`\lvert J \rvert` never falls
below 3.18 m while the root is bracketed to a factor 1.0015. **The stopping
rule is therefore the width of the bracket in the calibrated parameter, never
the size of the residual**; a search stopping on :math:`\lvert J \rvert <
\varepsilon` may never stop. The search walks the base-ten logarithm of the
parameter, and ``rel_tol`` becomes a width in that variable, so a ``rel_tol``
of 0.01 closes the bracket at one per cent on the parameter itself, which is
the paper's criterion read literally. On any other transform that width would read
as an absolute one, and the adapter refuses a parameter that does not declare
``transform = "log"`` rather than reporting convergence on a bracket orders of
magnitude wide.

**Monotonicity is not proven.** The paper establishes the direction of
variation on three points and generalises it over twenty-four catchments. A
coarse logarithmic sweep of ``sweep_points`` points, seven by default, is run
before the bisection: it checks the property instead of assuming it, it sees
every crossing rather than one, and the crossing curves come out of the same
solves. Several crossings warn and the tightest one is closed. Setting
``sweep_points`` to zero drops the sweep and brackets on the two bounds, which
is the pure bisection of the paper.

**A bracket without a sign change is a result.** The search first widens the
interval by a decade on each side, up to ``bracket_expand`` times, four by
default; if the sign still does not change it raises and prints both residuals
rather than returning the better of the two ends, because returning the better
end is a minimised mean distance in disguise. When the widening does find a
sign change, but only outside the declared bounds, the value comes back with a
warning naming how many expansions it took: a root several decades outside a
declared interval is rarely a surprising conductivity, it is usually the
residual failing to respond to the parameter at all. The next section names one
way that happens.

Why the ratio is what gets calibrated
-------------------------------------

Under a drain conductance proportional to :math:`K`, the steady balance of a
water-table cell is

.. math::

   \nabla \cdot (K\, d_{sat} \nabla h) + R = C\,(h - z_{top})
   \quad\text{with}\quad C = \frac{K A}{e}

and dividing by :math:`K` leaves a problem depending on :math:`R/K` and on the
geometry alone. So the head field, and therefore the seepage mask, depend only
on the ratio. Measured on a real catchment of 3 449 cells: multiplying
:math:`K` and :math:`R` by a common factor from 0.01 to 100 leaves the mask
**strictly identical, zero cells of difference**, and the head invariant to
5e-6 m. The same factor on :math:`K` alone moves 135 cells.

That proportionality is not a parasitic coupling to be corrected: it is what
makes "calibrating :math:`K/R`" well posed. A conductance fixed independently
of :math:`K` breaks the invariance from a factor 1.05 onwards.

Two consequences follow. A test of the invariance must assert on **the mask and
the head, never on the discharge**: mass balance forces the total discharge to
follow the recharge whatever the conductance, so a discharge-based test passes
on a model whose mask has half changed. And the seepage criterion is applied to
the **flux**, not to :math:`h \geq z_{top}`: the flux is anchored by the mass
balance and its median cell value holds over eight decades of conductance,
while :math:`h - z_{top}` travels twelve.

What the method needs from the flow model
-----------------------------------------

**Every package that releases groundwater to the surface has to reach the
criterion.** The simulated network is built from the release flux, so a package
whose outflow the criterion cannot read becomes a stretch of catchment read as
dry land, and it reads as dry precisely where that package drains, which is
where the criterion aims.

MODFLOW 6 makes that easy to do by accident. An advanced package given a
``budget_filerecord`` writes its exchange to its own file beside the model
budget, and the model budget then holds no record for it at all. Measured on
the Nancon with the streams in SFR: the aquifer released 2.10 m3/s in total,
1.33 of it through the stream package. Reading the model budget alone saw the
drain and nothing else, which made **63 per cent of the outgoing water
invisible** and left the criterion measuring a seepage network missing two
thirds of its water. That network was then a skeleton of prescribed reaches
that never retracted as the conductivity rose: the residual stayed positive
across the whole declared interval, and the search closed three decades above
it on a value that means nothing, with a validity indicator comfortably inside
its bound.

HydroModPy refuses rather than measure that. The requirement is read off the
budget file and not off the model object, which can be silent about a package
the run really built: a release record that no declared package covers, or a
sibling package budget sitting next to the model one, raises and names the
package. That is also what catches the next package the same way, without
naming it in advance.

What the criterion reproduces, and how far that goes
----------------------------------------------------

The Nancon was calibrated twice with nothing shared but the mapped network and
the forcing: MODFLOW-NWT on the catchment mesh, and MODFLOW 6 on a structured
grid. Over a parameter searched across four decades, the two roots are
:math:`K = 2.10 \times 10^{-4}` and :math:`1.87 \times 10^{-4}` m/s, **eleven
per cent apart**.

Both runs find exactly one sign change over the sweep, and each balances its
two error classes at the root, which is what the criterion is asked to do: 550
cells of excess against 517 missing under MODFLOW-NWT, 196 against 212 under
MODFLOW 6.

Read that for what it is. Eleven per cent over four decades of search is the
reproducibility of the criterion across a change of solver, of grid and of
discretisation. It is not the accuracy of the calibrated conductivity, which
the biases below bound far more loosely, and it says nothing about whether
either number is right.

Known biases, and how to read the output
-----------------------------------------

This section is not a disclaimer. Each point below was measured, and each one
changes how a number produced by this method may be reused.

**The method over-estimates the ratio, with a known sign.** Against a synthetic
truth where the model is exact, giving the closure of the true network back as
the observation recovers the ratio to 1.001. Giving a thinned network, which is
what every real hydrographic map is, biases the ratio by a factor 2.7 to 7.5,
and up to 23.7 when only a quarter of the true network is kept. The
dose-response is monotone. Since every real map is less dense than the true
network, the bias is present in every real application and it points the same
way.

**The validity ratio measures agreement, never correctness.** Measured on
synthetic truth, :math:`r_{optim}` **improves as the bias worsens**: 0.33, then
0.29, then 0.15 for biases of 7.5, 10.6 and 23.7. On eleven structural variants
of one model, all accepted by Equation 4, the calibrated ratio spans a factor
29, and the two best ratios belong to the two variants whose model top had been
altered. Do not read :math:`r_{optim}` as a quality indicator of the model.

**The validity ratio also moves with the grid, and it flatters the coarser
one.** Between the two runs of the section above, :math:`r_{optim}` went from
4.58 to 2.21 with nothing about the model improved: the coarser grid carries
larger cells, :math:`L_{ref}` is the square root of the median cell area, and
the denominator grew. Same catchment, same mapped network, indicator halved.
Refining a mesh therefore degrades the indicator at constant agreement, which
is what ``observed_position_accuracy`` is for: declaring the positional
accuracy of the mapped network floors :math:`L_{ref}` at a length the model
resolution cannot shrink. Two :math:`r_{optim}` values measured on different
meshes are not comparable unless that floor is declared and identical.

**Publish** :math:`T/R`, **not** :math:`K`. The conductivity inherits the
recharge series entirely: changing reanalysis moves it by +3, +25 and -28 per
cent on three catchments. On a five-layer model, :math:`T/R` is stable to 1.21
where the mean distance no longer separates anything. The ratio is not computed
for you: the calibration returns the conductivity raw in ``best_parameters`` and
emits the recharge that divides it as ``R_mean_m_s`` per trial, read back from
the built model rather than from the TOML, so forming :math:`T/R` and naming
that recharge series beside it is the author's work.

**The positional uncertainty of the mapped network is oriented.** Displacing it
by one cell moves the ratio by a factor 3.7 to 8.9 depending on the catchment,
and twelve estimates out of twelve came out at or above the nominal one. This
is a bias, not only a variance, and it is consistent with the thinning bias
above.

**There is an irreducible floor.** The mapped network is never contained in the
simulated one at any parameter value: twelve to nineteen per cent of the
linework stays dry for topographic reasons. On the one catchment rejected by
Equation 4, that floor accounts for 46 per cent of the ratio, so the rejection
measures a structural incapacity rather than a bad parameter.

**The two averages are tail statistics.** At the root, their median is exactly
zero and forty per cent of their value is carried by five per cent of the
cells, because the two networks share a common trunk. Reading
:math:`r_{optim} \leq 2` as "the typical gap is under two pixels" is wrong: the
typical gap is zero and the criterion lives in the tail. HydroModPy therefore
reports the median, the ninetieth percentile and the share carried by the top
five per cent beside each mean, as ``D_so_median``, ``D_so_p90`` and
``D_so_top5_share``, and the same three for :math:`D_{os}`.

**A second phase calibrating storage identifies** :math:`S_y/T`, **not**
:math:`S_y`. For an unconfined Dupuit aquifer the recession constant behaves as
:math:`S_y L^2 / T`, so a log-NSE on the recessions constrains the ratio. Freeze
a transmissivity biased by a factor :math:`f` and the storage comes out biased
by the same factor, with the objective function unchanged. What is wrong in
both cases is the stored volume, which is exactly the quantity long-term
projections rest on.

Domain of validity
------------------

Unconfined aquifers, temperate humid climate, gentle topographic gradients,
strong groundwater-stream connection, and a DEM whose resolution is compatible
with the positional accuracy of the mapped network. Outside that envelope the
criterion still computes, and it still means less.

The pre-treatment the method requires
-------------------------------------

The distances are measured along the flow paths of the DEM. If the mapped
linework does not sit in the talwegs of that DEM, they measure a disagreement
between two datasets rather than hydrogeology. The repair is on the DEM side,
by burning the network into the routing surface before conditioning, and it has
to be redone at every change of resolution.

The indicator is :math:`\alpha`, the ratio between the mapped network and its
own downslope closure. Measured with no pre-treatment on five catchments at
75 m: 0.68 to 0.95, so on four of five, a quarter to a third of the D8 trace
leaving the mapped cells exits the network at the first step. At 25 m it falls
to 0.49 to 0.64. The disagreement is the rule, not the exception.

HydroModPy measures :math:`\alpha` on every run declaring
``geographic.enforce_streams.stream_geometry_path``, whether or not ``enabled``
is set, which is what makes it usable to decide that the burning is needed. It
is written to ``stream_dem_agreement.json`` in the geographic directory and
logged with a warning below 0.90. A run declaring no network there measures
nothing. A calibration declaring a network output recomputes the same ratio on
the solver mesh and publishes it per trial as ``alpha_obs_closure``.

Burning and flooding are two different repairs, and neither replaces the other.
Burning fixes the registration between two datasets, once, on the routing
raster; the flood described above fixes the surface itself, on the mesh graph,
at every trial. A network burned into a routing raster still descends into the
pits the mesh grows when it reads that raster back, and a flooded mesh still
measures a dataset disagreement if the linework was never in the talwegs to
begin with.

References
----------

.. bibliography::
   :filter: docname in docnames
