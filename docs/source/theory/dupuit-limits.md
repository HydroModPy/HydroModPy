# Where Dupuit stops being true

A model with one layer, and the Boussinesq solver always, reads the aquifer
through the Dupuit assumption: the flow is horizontal and the head does not vary
with depth {cite:p}`dupuit1863,brutsaert2005`. That turns the three-dimensional
equation {eq}`eq-gwf-3d` into the one-layer equation {eq}`eq-boussinesq`. This
page says when that reading is fair, and where in a catchment it fails: a column
too thick for its flow path, the ground next to a stream, and the face where the
water table meets the land surface. It does not change what the code computes.

::::{dropdown} Notation of this page
```{hmp-notation}
```
::::

(dupuit-aspect)=
## The aspect ratio

Take a flow path of horizontal length $L_h$, from a divide to the stream that
drains it, through a saturated thickness $B$. Mass conservation ties the vertical
component $q_z$ of the Darcy flux to the horizontal one $q_x$: over the path, the
water that moves down or up is a share of order $B / L_h$ of the water that moves
along it, so $q_z \sim (B / L_h)\, q_x$. Darcy's law turns each component into a
head gradient, $\partial h/\partial x = -q_x / K$ and
$\partial h/\partial z = -q_z / K_z$. The head difference across the thickness,
$\delta h_z \sim B\,\lvert\partial h/\partial z\rvert$, compared with the head
difference along the path, $\delta h_x \sim L_h\,\lvert\partial h/\partial x\rvert$,
is then

$$
\frac{\delta h_z}{\delta h_x} \sim \beta \left(\frac{B}{L_h}\right)^{2},
\qquad \beta = \frac{K}{K_z} .
$$ (eq-dupuit-ratio)

The Dupuit assumption sets this ratio to zero. It is a fair reading of the
three-dimensional problem when the ratio is small. The anisotropy enters at first
power and the thickness at second power: a column ten times thinner than its path
gives a ratio of $\beta / 100$, so a ratio $\beta = 10$ already brings the vertical
head difference to one tenth of the horizontal one.

This is an estimate of order of magnitude, not a bound: the prefactor depends on
the shape of the recharge and of the outlet. It says which way the error goes. A
thick aquifer, a short hillslope, or a strong vertical anisotropy pulls the model
away from Dupuit.

(dupuit-streams)=
## Next to a stream

The same ratio, read with a local length $\ell$ instead of $L_h$, says over which
distance the flow is not horizontal. Water that converges on a stream bends
upwards in a zone where $\beta (B / \ell)^2$ is of order one, that is within

$$
\ell \sim B\,\sqrt{\beta}
$$ (eq-dupuit-stream)

of the stream. Inside that zone the head varies with depth, and the head under
the stream is higher than the stream stage. A one-layer model has no such zone:
each cell next to the stream carries one head. The resistance of the converging
flow is then left to the conductance of the drain or of the stream cell
({doc}`exits`). With $B = 30$ m and $\beta = 10$, the zone is about 100 m wide,
the size of one or two cells of a 75 m grid.

(dupuit-seepage)=
## The seepage face

Where the water table meets the land surface, on a slope or a stream bank, water
leaves the ground over a seepage face that stands above the stream. Under the
Dupuit assumption, a fixed head at the stream puts the water table at the stream
level at the bank, so the computed water table near the outlet is too low and has
no seepage face.

In HydroModPy the water table leaves the ground wherever it reaches the land
surface: the drains of the top layer ({doc}`exits`) and the surface closures of
the Boussinesq solver ({doc}`boussinesq`) remove the water that rises above
$z_\mathrm{top}$. The seepage face is then the set of cells that drain, at the
scale of a cell. Inside a cell there is no seepage face: the outflow sits at the
top of the cell, and a stream imposed as a head fixes the head of the whole
stream cell.

(dupuit-topography)=
## When the water table follows the topography

{cite:t}`haitjema2005subdued` use the Dupuit-Forchheimer approximation to tell a
water table that follows the land surface from one that the recharge controls.
Written with the symbols of this site, their criterion is

$$
\frac{N\,L_h^{2}}{m_s\,K\,H\,\Delta z_\mathrm{max}} > 1
\quad \text{(the water table follows the topography)},
$$ (eq-haitjema)

with $L_h$ the distance between the streams, $H$ the mean aquifer thickness,
$\Delta z_\mathrm{max}$ the largest rise of the land surface above the streams,
and $m_s = 8$ for a flow in one direction or $16$ for a radial one. Above 1, the
water table reaches the land surface over a large share of the catchment, and the
drains of the model carry much of the outflow. Below 1, it stays under the land
surface, and the drains act along the streams only. The criterion rests on the
Dupuit assumption, so it holds where {eq}`eq-dupuit-ratio` is small.

## What the code offers

- **Layers.** With {toml}`modflow6.sgrid.vertical.nlay` above 1 and a ratio
  {toml}`modflow6.process_specific.vka`, MODFLOW 6 and MODFLOW-NWT solve
  {eq}`eq-gwf-3d` with one head per layer. The head can then vary with depth from
  one layer to the next, and the vertical resistance of {eq}`eq-dupuit-ratio`
  enters the solution. Each layer still has one head.
- **One layer, or the Boussinesq solver.** The model is Dupuit by construction.
  Check {eq}`eq-dupuit-ratio` with the thickness of the depth model and the length
  of the hillslopes before you read the heads near a stream.
- **No seepage face on a bank.** The outflow leaves through the top of the cells.

## Assumptions

- The estimates of this page are scalings, without a prefactor.
- The aquifer is homogeneous over the flow path, with a ratio $\beta$ that does
  not change with depth.
- The criterion of {eq}`eq-haitjema` takes a uniform recharge and a uniform
  thickness, as its authors do.

## Limits

- **No check in the code.** HydroModPy computes none of the ratios of this page,
  and refuses no model for its aspect ratio.
- **A depth factor changes the estimate.** A conductivity that decays with depth
  ({eq}`eq-depth-factor`) carries most of the flow near the top, so the thickness
  that matters is shorter than $B$.

## See also

- {doc}`groundwater-flow`: the equations this page reads.
- {doc}`exits`: the drains and the streams the water leaves through.
- {doc}`mesh`: the cell sizes the stream zone of {eq}`eq-dupuit-stream` compares with.
