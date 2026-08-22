Downslope-distance calibration of the stream network
====================================================

This page explains the criterion that calibrates a catchment against the
spatial extent of its stream network rather than against a gauge
:cite:`abherve2023`, and how to read what it returns. It has a companion in
:doc:`network-metrics-and-extreme-k-sweep`, which covers the overlap metrics
that answer a different question.

Read it before running the method, and read the section on known biases before
reusing a number it produced.

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
bracket and there is no root left to close. The outlet is not a product of the
DEM, it is the closing point of the catchment, so writing that it belongs to
the stream network is true by definition.

**Both supports are intersected with the topographic catchment.** On a buffered
model domain, ten to fifteen per cent of cells drain outside the basin and
never meet the mapped network; on the catchment alone the figure falls to a
fraction of a per cent. Measured on one real mesh: 14.9 per cent against 0.11
per cent. Without the intersection the unreachable guard aborts on every real
catchment.

**Water bodies stay in the graph and in the target, and leave both supports.**
A hillslope cell upstream of a reservoir has to be able to descend through it,
and open water must absorb a path that reaches it, but a line of hydrography
drawn across a reservoir is not the observation of a stream. Keeping lake cells
in the support of :math:`D_{so}` would inject one zero per lake cell and move
the root with the size of the reservoir.

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
denominator without improving the agreement.

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
end is a minimised mean distance in disguise.

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

**Publish** :math:`T/R`, **not** :math:`K`. The conductivity inherits the
recharge series entirely: changing reanalysis moves it by +3, +25 and -28 per
cent on three catchments. On a five-layer model, :math:`T/R` is stable to 1.21
where the mean distance no longer separates anything. The ratio is not computed
for you: the calibration returns the conductivity raw in ``best_parameters`` and
emits neither the ratio nor the recharge that divides it, so forming
:math:`T/R` and naming that recharge series beside it is the author's work.

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

References
----------

.. bibliography::
   :filter: docname in docnames
