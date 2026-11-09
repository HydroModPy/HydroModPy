# The linear reservoir, a global flow model

One cell takes the whole catchment: the mesh that follows the catchment
itself builds it, `[mesh]` with no engine line meets it, and the one of a
mesh of more cells is refused. The solve reads the `Model` and its own
options table and nothing else.

## What it solves

The state is the depth of water on the cell. One piece of constant rate
advances by the closed form `tau * r + (s - tau * r) * exp(-dur / tau)`,
never by a substep, so the mass of the run closes to the arithmetic of one
exponential. The run writes one discharge and one reservoir storage per
period at the station of the whole catchment, and the budget rows of the
terms recharge, drain and storage at the domain zone.

Its time constant is set in `[solver.linear_reservoir]` per document, the
read accepts a bare number of days and a string with its unit, and the
calibration of a site walks it in the log space.
