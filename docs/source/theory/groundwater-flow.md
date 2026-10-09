# The groundwater flow problem

What head does the aquifer hold, in every cell and at every time? This page gives
the equation HydroModPy solves for that head, the geometry it is solved on, the
properties that enter it and the state it starts from. For the same subject in
plain words, see {doc}`../understand/what-it-computes`. What each solver supports
is listed in {doc}`../reference/solvers`.

:::{note}
**Scope.** Three solvers read the same `[flow]` section: MODFLOW 6 (the default),
MODFLOW-NWT and the in-house Boussinesq solver. They solve the same physical
problem and not the same discrete equations. The problem is written once here,
with the discrete form of the two MODFLOW solvers in
{ref}`gwf-discrete`. The Boussinesq form is on {doc}`boussinesq`. What enters and
leaves the aquifer (recharge, drains, streams, lakes, wells) has its own pages:
{doc}`forcing`, {doc}`soil-reservoir` and {doc}`exits`. Where the one-layer
equation stops being true is on {doc}`dupuit-limits`.
:::

::::{dropdown} Notation of this page
Lengths are in metres, time in seconds, and elevation is positive up. A key
accepts a value with its unit ("30 m", "5 m/day"); the code converts it before it
builds the solver input. Every symbol of the site is on {doc}`notation`.

```{hmp-notation}
```
::::

(gwf-domain)=
## The domain

Two surfaces bound the aquifer.

**The top** $z_\mathrm{top}$ is the digital elevation model of the catchment,
read from {toml}`data.dem`. By default the grid takes the value of the DEM at the
centre of each cell, and nothing else moves the top.
{toml}`modflow6.sgrid.top_sampling.mode` can ask for a statistic over the pixels
of the cell instead, with a lower value for the cells that hold a channel
({ref}`mesh-top`).

**The bottom** $z_\mathrm{bot}$ comes from a depth model, chosen by
{toml}`domain.depth_model.kind`. Four kinds exist:

| Kind | Bottom | Reads |
|---|---|---|
| `constant_thickness` | $z_\mathrm{bot} = z_\mathrm{top} - H_c$ | {toml}`domain.depth_model.thickness` |
| `flat_substratum` | $z_\mathrm{bot} = z_s$ | {toml}`domain.depth_model.substratum_elevation` |
| `raster_substratum` | $z_\mathrm{bot} = \min\bigl(Z_r + \zeta,\ z_\mathrm{top} - H_\mathrm{min}\bigr)$ | the raster of {toml}`data.substratum`, in metres, on the datum of the DEM |
| `raster_thickness` | $z_\mathrm{bot} = \min\bigl(z_\mathrm{top} - \lambda Z_r + \zeta,\ z_\mathrm{top} - H_\mathrm{min}\bigr)$ | the raster of {toml}`data.substratum`, in metres below the top |

A flat substratum is an elevation, not a depth: where the land surface drops under
it, no aquifer is left. A raster kind:

1. reprojects the raster onto the grid of the top;
2. refuses the run if one cell of the domain has no raster value, so the raster
   must cover the whole extent of the domain, buffer included when
   {toml}`geographic.domain_extent` is `"box"`;
3. applies $\lambda$ and $\zeta$;
4. lowers the bottom to $z_\mathrm{top} - H_\mathrm{min}$ wherever it would
   come closer to the top than that, and logs a warning that counts the cells;
5. refuses the run if every cell needs that correction, since no aquifer would
   remain.

```{eval-rst}
.. plot:: theory/figures/gwf_depth_models.py
   :alt: Four cross-sections of one valley, each with the top and the bottom of the aquifer that one depth model gives.
   :caption: The four depth models on one valley, as ``build_domain`` returns them. Look at the
      valley floor of the two raster kinds: where the raster bottom (dotted) comes within
      :math:`H_\mathrm{min}` of the top (8 m here), the cells (dots) are lowered to
      :math:`z_\mathrm{top} - H_\mathrm{min}`.
```

Take a top of 120 m everywhere and a raster that holds 40 m, or 85 m for the
elevation kind, in every cell but one. The table gives the bottom of that cell, as
`build_domain` returns it (the check ran the function).

| Depth model | Raster value | $\zeta$, $\lambda$ | Bottom |
|---|---|---|---|
| `raster_thickness` | 40 m | 5 m, 1 | 85 m |
| `raster_thickness` | 40 m | 0 m, 2 | 40 m |
| `raster_thickness` | 0.5 m, with $H_\mathrm{min} = 1$ m | 0 m, 1 | 119 m, with a warning |
| `raster_substratum` | 85 m | -5 m | 80 m |

A raster kind needs the raster. {toml}`data.substratum` takes exactly one source.
A file that inherits a constant thickness removes it with `thickness__delete`
when it switches to a raster (see {doc}`../reference/parameters/grammar`):

```toml
base_config = "step4_transient.toml"

[domain.depth_model]
thickness__delete = true
kind = "raster_thickness"
min_thickness = "2 m"

[[data.substratum.sources]]
source = "custom"
path = "substratum/thickness.tif"
```

The thickness of an aquifer is an assumption in this model, not a result. No
equation below estimates it. The field of the constant thickness declares itself
calibrable, in log space. In the code: `Domain._build_surfaces`.

(gwf-layers)=
## The solver grid and its layers

The grid samples $z_\mathrm{top}$ and $z_\mathrm{bot}$ at the centre of each cell
(the cell layout is on {doc}`mesh`). A cell with no finite value in either
surface becomes inactive in every layer. The grid is refused when
$z_\mathrm{bot} \ge z_\mathrm{top}$ on a valid cell. On a runtime mesh, a warning
names the columns thicker than 500 m and than 10 times the median: a raster
nodata value read as an elevation produces them ({ref}`mesh-acceptance`).

The thickness is then cut into $n_\mathrm{lay}$ layers. The bottom of layer $j$ is

$$
z_{\mathrm{bot},j} = z_\mathrm{top} - H\,p_j ,
\qquad p_{n_\mathrm{lay}} = 1 .
$$ (eq-layer-bottom)

The shares $p_j$ are the same for every cell. Three rules build them, chosen by
{toml}`modflow6.sgrid.vertical.genmtd_lay`:

| `genmtd_lay` | $p_j$ |
|---|---|
| `constant` | $j / n_\mathrm{lay}$ |
| `decay`, with $\rho$ read from {toml}`modflow6.sgrid.vertical.lay_decay` | $(1 - \rho^{j}) / (1 - \rho^{n_\mathrm{lay}})$ |
| `list` | the running sum of {toml}`modflow6.sgrid.vertical.lay_proportions` |

The `decay` rule needs $\rho > 1$, and the file is refused otherwise: the layers
then thicken with depth. With $\rho = 2$ and four layers they hold 1, 2, 4 and 8
fifteenths of the column, from the top down. A `list` must sum to 1. With one
layer, $p_1 = 1$ and the column is one cell. MODFLOW-NWT reads the same keys
under `modflownwt.sgrid.vertical`.

```{eval-rst}
.. plot:: theory/figures/gwf_layers.py
   :alt: Four columns of 100 m, each cut into four layers by one rule.
   :caption: Four layers in a column of 100 m, from ``_compute_layer_proportions``. Look at
      the decay columns: the larger :math:`\rho`, the thinner the top layer and the thicker
      the bottom one.
```

```toml
base_config = "step4_transient.toml"

[modflow6.sgrid.vertical]
genmtd_lay = "decay"
nlay = 4
lay_decay = 2.0
```

**What the layers can and cannot represent.** Every layer reuses the planar cells
and their connections, and only the top and the bottom of the column vary from
cell to cell. The internal interfaces follow one rule of proportions over the
whole model, so the layers follow the relief and the substratum and never pinch
out. Geology therefore varies through the properties of each layer and cell
({ref}`gwf-properties`), not through surfaces of its own. A stratigraphy whose
interfaces cross the proportions, a layer that disappears, or a connection that
changes from one layer to the next is not represented. MODFLOW 6 builds every
grid, structured or not, as a vertex grid (`DISV`), never as `DISU`. The
Boussinesq solver has no layers: it works on one triangle per column. In the
code: `_compute_layer_proportions`.

(gwf-properties)=
## The properties

Each property is a field: one value for the whole domain, or one value per zone
({doc}`[flow.param] <../reference/parameters/flow/param>`). How a zone map becomes one value per cell is on
{doc}`solvers/field-to-cell-parameter-transfer`.

| Property | Needed by a steady run | Needed by a transient run |
|---|---|---|
| MODFLOW 6 and MODFLOW-NWT | $K$ | $K$, $S_y$, $S_s$ |
| Boussinesq | $K$ | $K$, $S_y$ |

The Boussinesq solver reads no $S_s$. In a steady MODFLOW run, a missing $S_y$ or
$S_s$ is filled with zero. In a transient run, a missing one stops the run.
Example 04 gives the three values, one for the whole catchment:

```{hmp-resolved} flow.param.K.field.value
:config: step4_transient.toml
```

```{hmp-resolved} flow.param.Sy.field.value
:config: step4_transient.toml
```

```{hmp-resolved} flow.param.Ss.field.value
:config: step4_transient.toml
```

**A depth factor.** A property can carry a `field_vertical_profile`. The value
of layer $j$ in a column is the value of the field times $f(d_j)$, where $d_j$ is
the depth of the middle of the layer below $z_\mathrm{top}$. For
`mode = "exponential"`:

$$
f(d) = e^{-d/d_c}, \qquad \text{or } \max\bigl(e^{-d/d_c},\ f_\mathrm{min}\bigr)
\text{ when } f_\mathrm{min} \text{ is set.}
$$ (eq-depth-factor)

Without {toml}`min_factor|flow.param.K.field_vertical_profile.min_factor`, the
factor has no floor and tends to zero with depth. For `mode = "tabulated"`, the
factor is a linear or stepwise interpolation of the table you give, equal to the
first and last factor outside the table. With one layer, $d_j$ is half the
thickness: the profile then gives one factor per cell and no variation with
depth.

```{eval-rst}
.. plot:: theory/figures/gwf_depth_factor.py
   :alt: The exponential depth factor against depth, with and without a floor, and the value of each layer.
   :caption: The depth factor for :math:`d_c = 20` m, from ``FieldParam.vertical_factor``.
      Each layer of a four-layer decay column takes the factor at its centre (dots), not
      an average over its thickness. Look at the deepest layer: without a floor its
      factor would be 0.03, with :math:`f_\mathrm{min} = 0.05` it stays at 0.05.
```

**Vertical conductivity.** MODFLOW 6 reads $K_z = K / \beta$, with $\beta$ the
{toml}`modflow6.process_specific.vka`, layer by layer, so a depth factor on $K$
reaches $K_z$. A parameter with the id `Kv` replaces it with a conductivity per
cell, and a file that gives `Kv` and a `vka` other than 1 is refused.

```toml
base_config = "step4_transient.toml"

[modflow6.process_specific]
vka = 10.0

[flow.param.K.field_vertical_profile]
mode = "exponential"
characteristic_depth = "20 m"
min_factor = 0.05
```

The code refuses a $K$ that is zero, negative or not finite on an active cell. A
heterogeneous $K$ whose zones do not cover the whole domain produces exactly that.
In the code: `FieldParam.vertical_factor`.

(gwf-equation)=
## The flow equation

Water is incompressible and its density is constant. Darcy's law gives the
specific discharge $\mathbf{q} = -\mathbf{K}\,\nabla h$. Mass conservation in a
porous medium gives the equation of the three-dimensional problem, written for
the head $h$ (the form of the MODFLOW documentation,
{cite:p}`harbaugh2005,langevin2017`):

$$
S_s\,\frac{\partial h}{\partial t}
= \frac{\partial}{\partial x}\!\left(K\,\frac{\partial h}{\partial x}\right)
+ \frac{\partial}{\partial y}\!\left(K\,\frac{\partial h}{\partial y}\right)
+ \frac{\partial}{\partial z}\!\left(K_z\,\frac{\partial h}{\partial z}\right)
+ W .
$$ (eq-gwf-3d)

$W$ is the net volume of water that the stress packages add per unit volume and
time. The conductivity is the same along $x$ and $y$.

In a catchment the aquifer is mostly unconfined. The head can sit below the top
of a cell, and then the thickness that carries flow is the saturated thickness

$$
B(h) = \min\bigl(\max(h - z_\mathrm{bot},\ 0),\ H\bigr) .
$$ (eq-saturated-thickness)

Every cell of the model is declared convertible: it can be full or partly dry
(`icelltype = 1` in the MODFLOW 6 `NPF` package, `iconvert = 1` in `STO`,
`laytyp = 1` in the MODFLOW-NWT `UPW` package). Two things then depend on the
head. The flow depends on it through $B$. The storage depends on it because a
falling water table releases water from the pores, which the specific yield $S_y$
measures, while a head above the top of a full cell only decompresses water and
the matrix, which $S_s$ measures. For a column one layer thick, integrating
{eq}`eq-gwf-3d` over the thickness gives the Boussinesq equation
{cite:p}`boussinesq1877,boussinesq1904`, with the Dupuit assumption that the head
does not vary with depth {cite:p}`dupuit1863,brutsaert2005`:

$$
\bigl(S_s\,B + S_y\,\chi\bigr)\,\frac{\partial h}{\partial t}
= \nabla\!\cdot\!\bigl(K\,B\,\nabla h\bigr) + q_\mathrm{net} ,
\qquad
\chi = \begin{cases} 1 & z_\mathrm{bot} < h < z_\mathrm{top},\\ 0 & \text{otherwise.}\end{cases}
$$ (eq-boussinesq)

$q_\mathrm{net}$ is the net flux per unit of plan area from the stress packages,
in m/s. The product $K\,B$ is the transmissivity $T$. When the water table is
inside the cell, the $S_s B$ term is small against $S_y$: in example 04,
$S_y = 0.05$ and $S_s B \le 3 \times 10^{-4}$, a ratio of about 170. The steady
problem drops the left-hand side. When {eq}`eq-boussinesq` is no longer a good
reading of {eq}`eq-gwf-3d` is the subject of {doc}`dupuit-limits`.

```{eval-rst}
.. plot:: theory/figures/gwf_saturated_thickness.py
   :alt: Saturated thickness and storage coefficient of one cell plotted against its head.
   :caption: One cell, with :math:`z_\mathrm{bot} = 70` m, :math:`z_\mathrm{top} = 100` m,
      :math:`S_y = 0.05` and :math:`S_s = 10^{-5}` m⁻¹. Left: :math:`B(h)`, the clipped
      thickness of :eq:`eq-saturated-thickness`. Right: the storage term of
      :eq:`eq-boussinesq`, on a log scale. Look at the drop at the top: once the cell is
      full, a rise of the head stores about 170 times less water.
```

(gwf-discrete)=
## The discrete problem in MODFLOW 6 and MODFLOW-NWT

Both solvers integrate the equation by control volumes, with one head per cell at
its centre. For a cell $n$, the balance of one time step is

$$
\sum_{m \in \mathcal{N}(n)} G_{nm}\,(h_m - h_n)
+ \sum_{p} \Phi_{n,p}
= \frac{1}{\delta t}\Bigl[\,S_s\,a_n\,B_n\,(h_n - h_n^\mathrm{old})
+ S_y\,a_n\,(B_n - B_n^\mathrm{old})\Bigr] .
$$ (eq-cell-balance)

The left side is the water that enters the cell during the step: the exchange with
the neighbours and the stress packages. The right side is the change of the volume
stored. $h^\mathrm{old}$ is the head at the start of the step. This is the one
statement of the balance on the site; the solver pages refer to it. The exact
weight of the saturation inside the step is the one of {cite:t}`langevin2017`,
and the smoothing of $B$ near the bottom of a cell is on {doc}`mf6-vs-nwt`.

**Conductance.** Between two cells of a layer, MODFLOW 6 keeps its default cell
averaging (HydroModPy sets no `CELL_AVERAGING` option), which joins the two
half-cell conductances in series. Without Newton, each half cell carries its own
saturated thickness:

$$
\frac{1}{G_{nm}}
= \frac{c_{nm}}{K_n\,B_n\,w_{nm}}
+ \frac{c_{mn}}{K_m\,B_m\,w_{nm}} ,
$$ (eq-conductance)

with $w_{nm}$ the width of the shared face and $c_{nm}$ the distance from the
centre of $n$ to that face. Under the Newton formulation, the default here, the
series is built with the full cell thicknesses and then multiplied by the
saturated fraction of the upstream cell, the one with the higher head (upstream
weighting, {cite:p}`langevin2017`). Between two layers, the series applies with
$K_z$ and the area of the shared face. A cell with $B_n = 0$ carries no flow out of
it. On Voronoi cells the face is the perpendicular bisector of the two centres,
which is the case the two-point form needs. Where it is not, the error and the
XT3D correction are on {doc}`solvers/xt3d-on-irregular-disv-meshes`.

```{eval-rst}
.. plot:: theory/figures/gwf_conductance.py
   :alt: Two neighbouring cells in plan and in section, with the lengths that enter their conductance.
   :caption: The lengths of :eq:`eq-conductance`. In plan, :math:`c_{nm}` and :math:`c_{mn}`
      go from each centre to the shared face of width :math:`w_{nm}`; they differ when the
      cells differ in size. In section, cell :math:`n` holds the higher head, so it is the
      upstream cell whose saturated fraction scales the conductance under Newton.
```

**Newton.** The balance is nonlinear in $h$, through $B$ and through the switch
$\chi$. MODFLOW 6 solves it with the Newton-Raphson formulation by default, with
under-relaxation, since every cell is convertible. MODFLOW-NWT is the Newton
formulation of MODFLOW-2005 {cite:p}`niswonger2011,harbaugh2005`, on the same
convertible layers and a structured grid. The iteration and its stopping tests
are on {ref}`solvers-newton-ims`.

**A cell by hand.** Take one layer, $a_n = 2500$ m², $z_\mathrm{bot} = 70$ m,
$z_\mathrm{top} = 100$ m, $S_y = 0.05$ and $S_s = 10^{-5}$ m⁻¹. Over one step of
30 days the head falls from 95 m to 94 m, and $B$ from 25 m to 24 m.

| Term | Value |
|---|---|
| $S_y\,a_n\,(B_n - B_n^\mathrm{old})$ | $0.05 \times 2500 \times (-1) = -125$ m³ |
| $S_s\,a_n\,B_n\,(h_n - h_n^\mathrm{old})$ | $10^{-5} \times 2500 \times 24 \times (-1) = -0.6$ m³ |
| Release over the step | $-125.6$ m³, or $-4.8 \times 10^{-5}$ m³/s |

The cell loses 125.6 m³ of water, and the specific storage accounts for 0.5 per
cent of it. The first row is the value of `_stored_saturated_volume_m3` of the
Boussinesq solver for these numbers; the second row is the formula above, not a
run of MODFLOW 6. In the code: `run_pre_processing`.

**The Boussinesq solver** writes the same balance on triangles, with a residual
that counts a loss as positive. Its edge flux takes the harmonic mean of $K$ and
the arithmetic mean of $B$ of the two cells, where MODFLOW takes $K\,B$ per half
cell, and its storage has no $S_s$. Its full derivation is on {doc}`boussinesq`.

(gwf-time)=
## Time

The run is cut into stress periods of length $\Delta t$, one per forcing value
({doc}`forcing`). Within a period the forcing is constant. Each period is cut into
$n_\mathrm{sub}$ equal time steps $\delta t = \Delta t / n_\mathrm{sub}$, and the
time integration is the backward Euler scheme: {eq}`eq-cell-balance` is written
with the stress and the conductances at the end of the step. The time step
multiplier is 1, so the steps of a period are equal. The one exception is
{toml}`modflow6.runtime.mf6_ats`: with it, MODFLOW 6 may cut a transient step
further where the solver does not converge, never above the step asked for. The
Boussinesq solver takes one step per period.

```{hmp-params}
simulation.time.step_value
simulation.time.substeps_per_period
```

The solver time step is a numerical choice: a period solved in one step differs
from the same period in several. {ref}`solvers-time` gives the size of that
difference on a test case.

{toml}`flow.flow_regime` picks the regime. In a `steady` run, every period is
steady. In a `transient` run, {toml}`flow.first_period_steady` marks the first
period as steady in the two MODFLOW solvers; the Boussinesq solver does not read
it and solves every period as a transient step. In a steady period the right side
of the balance is zero, the storage plays no part, and the heads settle where the
forcing of that period puts them. Example 04 states the regime:

```{hmp-resolved} flow.flow_regime
:config: step4_transient.toml
```

In the code: `sto_period_settings`.

(gwf-start)=
## The starting heads

The head at the start of the run, $h_0$, is declared in the flat table `[flow.ic]`.
Its value is the same in every layer of a column. `bottom` is the bottom of the
deepest layer.

| `type` | $h_0$ |
|---|---|
| `top` | $z_\mathrm{top}$ |
| `top_offset` | $z_\mathrm{top} - v$, with $v$ the `value` |
| `bottom` | $z_{\mathrm{bot},n_\mathrm{lay}}$ |
| `custom` | $v$ |
| `steady_state` | the solution $h^\star$ of the steady problem under a constant recharge, see below |
| `spinup_cyclic` | the state a cyclic run settles at, see below |

In every case, a cell on an imposed head (an ocean, a stream or a side boundary)
starts at that head. `top` is a full aquifer; the card of {toml}`flow.ic.h.type`
gives the default.

**The equilibrium.** For `steady_state`, the code first solves an auxiliary
steady problem with the same solver, the same grid and the same properties. Its
recharge is a constant, set by {toml}`flow.ic.h.source`: the mean of the whole
record, or the rate that you state. The result is $h_0$:

$$
\nabla\!\cdot\!\bigl(K\,B(h^\star)\,\nabla h^\star\bigr) + \bar N + q_\mathrm{bc}(h^\star) = 0 ,
\qquad h_0 = h^\star ,
$$

where $\bar N$ is the constant recharge and $q_\mathrm{bc}$ the exchanges with
the boundaries per unit area, held at the value of the first period
({toml}`flow.ic.h.boundary_condition_policy`).

**The settled cycle.** For `spinup_cyclic`, the run repeats its own period. Cycle
$c + 1$ starts from the heads where cycle $c$ ended, $h_\mathrm{end}^{(c)}$, and
the first cycle starts from {toml}`flow.ic.h.first_cycle_from`. The loop stops when

$$
\max_n \bigl|\,h^{(c+1)}_{\mathrm{end},n} - h^{(c)}_{\mathrm{end},n}\,\bigr| \le \varepsilon_h ,
$$ (eq-spinup)

with $\varepsilon_h$ the {toml}`flow.ic.h.tol_head`, or after
{toml}`flow.ic.h.max_cycles` cycles. The maximum counts every cell, not the mean.

```{eval-rst}
.. plot:: theory/figures/gwf_spinup.py
   :alt: Largest and mean change of the end-of-cycle heads against the cycle number, with the tolerance.
   :caption: The stopping test of :eq:`eq-spinup`, applied by ``cycles_have_settled`` to 200
      cells of which 10 drift slowly. Look at the two curves: the mean change falls under
      :math:`\varepsilon_h` at cycle 6, the largest change only at cycle 10, and
      the largest change decides. With the default of 4 cycles, this loop would stop
      before it settles.
```

**When the first period is steady.** With {toml}`flow.first_period_steady` at its
default, period 0 is solved as a steady state, and the heads above are only the
first guess of that solve. They change the convergence and not the state reached.
To make the run start from a state you choose, write `first_period_steady = false`
(see {doc}`[flow.ic] <../reference/parameters/flow/ic>`).

```toml
base_config = "step4_transient.toml"

[flow]
first_period_steady = false

[flow.ic]
type = "steady_state"
```

A run can also restart from the last time step of an earlier run
({toml}`flow.restart_from`). That state replaces $h_0$. In the code:
`build_head_initial_condition_array`.

(gwf-stress)=
## What enters and leaves

The stress terms $\Phi_{n,p}$ and the source $W$ of the equations above come from
packages. Each one has its page.

| Term | MODFLOW 6 package | Page |
|---|---|---|
| Recharge $N$ | `RCHA` | {doc}`forcing`, {doc}`soil-reservoir` |
| Evapotranspiration that the soil did not meet, or a negative recharge routed to evaporation | `EVTA` | {doc}`soil-reservoir`, {doc}`forcing` |
| Drainage at the land surface | `DRN` | {doc}`exits` |
| Imposed heads: ocean, stream, sides | `CHD` | {doc}`exits` |
| Wells | `WEL` | {doc}`exits` |
| Stream reaches, lakes, flow barriers, water transfers | `SFR`, `LAK`, `HFB`, `MVR` | {doc}`exits` |

Recharge and injection are positive when water enters the aquifer, and a well with
a negative rate pumps. Where no boundary is activated, the edge of the domain
carries no flow. The two keys that activate them are {toml}`flow.active_bc` and
{toml}`flow.active_sinks_sources`. A boundary prescribes a head and lets the flow
emerge. Drainage is a head-dependent exchange. Recharge and evapotranspiration are
areal rates. A well is a volume per unit of time.

## Assumptions

- The water is incompressible and its density is constant. The conductivity does
  not change with time or with the head.
- The conductivity is the same along the two horizontal axes. Only the vertical
  one differs, by the ratio $\beta$ or by the parameter `Kv`.
- Each cell holds one head, at its centre. The flow between two cells is a
  conductance times a head difference.
- With one layer, the flow is horizontal and the head does not vary with depth
  (the Dupuit assumption, {doc}`dupuit-limits`).
- The specific yield releases its water at once when the water table falls. There
  is no delayed yield.
- The thickness of each cell does not change in time: no compaction.
- The layers share one plan grid and one rule of proportions, so geology varies
  through properties and never through surfaces.
- The forcing is constant over a stress period.
- The bottom and the sides of the domain are impervious, except where a boundary
  is activated.
- The thickness of the aquifer is chosen, not computed.

## Limits

- **Shallow and unconfined.** Every cell is convertible. The code is built for the
  saturated zone of a catchment, from the surface down to a substratum that you
  place.
- **No unsaturated flow.** The code builds no `UZF` package. The water that reaches
  the water table is a recharge, given or computed by the daily soil store of
  {doc}`soil-reservoir`.
- **No density-dependent flow, no compaction.** The code builds neither a `BUY`
  nor a `CSUB` package.
- **A bottom above the top is refused.** So is a bottom that equals it, and a
  raster that leaves one cell without a value.
- **Layers cannot pinch out.** The same proportions apply in every column, and the
  thickness cannot fall below $H_\mathrm{min}$ with a raster kind.
- **Boussinesq has one layer and no $S_s$.** It reads $K$ and $S_y$ only.
- **Newton and rewetting exclude each other** in MODFLOW 6.
- **A steady first period is refused with the soil reservoir.** The reservoir
  sends a daily recharge that is zero after a dry day, and a one-period steady
  state would start the run from a drained aquifer.
- **Each solver has its own boundaries.** The file is refused when the solver
  cannot carry a boundary it asks for.

## Parameters of this page

The fields below are the ones that appear in the equations. Open a row for its
card.

```{hmp-params}
domain.depth_model.kind
domain.depth_model.thickness
domain.depth_model.substratum_elevation
domain.depth_model.offset
domain.depth_model.min_thickness
domain.depth_model.scale
data.substratum.sources.path
modflow6.sgrid.vertical.nlay
modflow6.sgrid.vertical.genmtd_lay
modflow6.sgrid.vertical.lay_decay
modflow6.sgrid.vertical.lay_proportions
flow.param.K.field.value
flow.param.Sy.field.value
flow.param.Ss.field.value
flow.param.K.field_vertical_profile.mode
flow.param.K.field_vertical_profile.characteristic_depth
flow.param.K.field_vertical_profile.min_factor
modflow6.process_specific.vka
flow.flow_regime
flow.first_period_steady
flow.ic.h.type
flow.ic.h.value
flow.ic.h.source
flow.ic.h.boundary_condition_policy
flow.ic.h.max_cycles
flow.ic.h.tol_head
flow.ic.h.first_cycle_from
flow.restart_from
```

## Checked by

The tests that import the code of this page. The box is generated: a new test
appears here on the next build.

```{hmp-tested-by}
hydromodpy.physics.flow
hydromodpy.spatial.domain
hydromodpy.spatial.field.core.field_param
hydromodpy.solver.field_property_mapping
hydromodpy.solver.modflow_grid
hydromodpy.solver.initial_conditions
hydromodpy.solver.steady_initial_conditions
hydromodpy.solver.modflow6.build
hydromodpy.solver.modflow_nwt.nwt
```

## In the code

| What | Where |
|---|---|
| The top, the bottom and the raster depth models | `hydromodpy/spatial/domain/domain.py` (`Domain._build_surfaces`, `Domain._substratum_from_raster`), `hydromodpy/spatial/domain/depth_model_config.py` |
| Reading the substratum raster | `hydromodpy/spatial/domain/build.py` (`read_substratum_source`) |
| Layers, the check bottom below top | `hydromodpy/solver/modflow_grid/discretization_spatial.py` (`_compute_layer_proportions`, `_assert_bottom_below_top`, `build_spatial_discretization`) |
| The properties, per cell and per layer | `hydromodpy/solver/modflow6/support/property_mapping.py` (`resolve_k33_field`), `hydromodpy/solver/field_property_mapping.py`, `resolve_required_flow_properties` |
| The depth factor | `hydromodpy/spatial/field/core/field_param.py` (`FieldParam.vertical_factor`), `SolverMesh.layer_center_depths` |
| The MODFLOW 6 balance: `NPF`, `STO`, `IC`, Newton | `hydromodpy/solver/modflow6/build.py` (`run_pre_processing`, `newton_options`) |
| The MODFLOW-NWT balance: `UPW` | `hydromodpy/solver/modflow_nwt/nwt/_pre_processing.py` |
| Steady and transient periods | `hydromodpy/solver/modflow_grid/discretization_temporal.py`, `hydromodpy/solver/modflow6/builders/period_forcing.py` (`sto_period_settings`) |
| The starting heads | `hydromodpy/solver/initial_conditions.py`, `hydromodpy/solver/steady_initial_conditions.py` (`cycles_have_settled`), `hydromodpy/solver/modflow6/builders/initial_conditions.py` (`build_start_heads`) |

## See also

- {doc}`dupuit-limits`: where the one-layer equation stops being true.
- {doc}`solvers`: what each solver adds to this problem.
- {doc}`mf6-vs-nwt`: where MODFLOW 6 and MODFLOW-NWT differ.
- {doc}`boussinesq`: the in-house solver in full.
- {doc}`../reference/parameters/flow/ic`: the keys of the starting state.
