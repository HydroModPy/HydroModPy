# Drains and evapotranspiration at the top of the model

Two exits act at the top of the model. A drain discharges where the water table
reaches the ground. The evapotranspiration package draws water where the water
table is shallow. Recharge is not an exit, but it is written by the same step of
the build and it decides what the drains carry, so it opens this page.

::::{dropdown} Notation of this page
```{hmp-notation}
```
::::

(drains-recharge)=
## Recharge in

MODFLOW 6 receives the recharge as one array per stress period (RCHA). The flux
into a column is $N_n a_n$. The package puts it on the top layer, and on the
first active layer below when the top cell is inactive. A lake cell is the case
where that would go wrong: its top layers are inactive, and the lake already
takes its own rain through LAK. The recharge is therefore set to zero on lake
cells, or the rain would be counted twice.

The recharge comes from a series or a grid that the run loads, or from the daily
soil reservoir of {doc}`../soil-reservoir`. How it becomes one value per stress
period, and how a negative recharge is split, is on {doc}`../forcing`.

In the code: `mask_recharge_on_lake_cells`.

(drains-et)=
## Evapotranspiration out

MODFLOW 6 and MODFLOW-NWT use the same law
{cite:p}`harbaugh2005,langevin2017`. The package draws water from a cell where
the water table is near the surface $z_\mathrm{et}$: at the full rate
$E^\mathrm{et}_n$ when the head is at or above $z_\mathrm{et}$, and at a rate
that falls linearly to zero at the depth $d_\mathrm{ext}$ below it:

$$
Q^{\mathrm{ET}}_n = a_n\, E^\mathrm{et}_n\, \kappa\!\left(\frac{h_n - (z_\mathrm{et} - d_\mathrm{ext})}{d_\mathrm{ext}}\right),
\qquad \kappa(x) = \min\bigl(1, \max(0, x)\bigr).
$$ (eq-evt)

Three sources feed it, each with its own surface and depth.

| Source | Rate $E^\mathrm{et}_n$ | Surface $z_\mathrm{et}$ | Depth $d_\mathrm{ext}$ |
|---|---|---|---|
| MODFLOW 6, deficit of a negative recharge | the deficit $N^-_k$ | $z_{\mathrm{top},n}$ | {toml}`evt_extinction_depth\|modflow6.process_specific.evt_extinction_depth` |
| MODFLOW 6, the ETP the soil reservoir left unmet | that residual ETP | $z^d_n - o_\mathrm{et}$ | {toml}`extinction_depth\|flow.sinks_sources.etp.extinction_depth` |
| MODFLOW-NWT, the loaded ETP and the deficit | the ETP as loaded, plus the deficit | $z_{\mathrm{top},n} - o_\mathrm{et}$ | {toml}`extinction_depth\|flow.sinks_sources.etp.extinction_depth` |

$z^d_n$ is the drain elevation of the cell (below): the top, or the top lowered by
half the band, and the top when the run has no drain. The surface of the soil
residual sits there because the soil has already taken the ETP it could, and
what is left may only draw from water that would otherwise reach the drain. The
card of {toml}`surface_offset|flow.sinks_sources.etp.surface_offset` says which
value applies to which solver.

The sea cells, the river cells and the lake cells carry no aquifer
evapotranspiration: a lake evaporates through LAK. The deficit of a negative
recharge is also kept off the cells that have no active layer.

The word `"etp"` in {toml}`flow.active_sinks_sources` acts differently by solver.
Under MODFLOW-NWT the loaded ETP drives the package. Under MODFLOW 6 it acts in
soil mode only, where it sends the residual ETP of the reservoir to EVTA; outside
soil mode MODFLOW 6 ignores it and logs a warning. The Boussinesq solver refuses
it.

In the code: `build_evt_array_stress_period_data`.

(drains-law)=
## The drain law

A drain removes water from a cell when the head is above the drain elevation
$z^d_n$, in proportion to the excess:

$$
Q^{\mathrm{drn}}_n = C_n \,\max\bigl(h_n - z^d_n,\ 0\bigr).
$$ (eq-drain)

This is the law of the DRN package of MODFLOW 6 and MODFLOW-NWT
{cite:p}`harbaugh2005,langevin2017`. It is one-sided: a drain never feeds the
aquifer. In HydroModPy the drain stands for seepage at the ground surface. There
is one row per cell, in the top layer, at the elevation of the top. The cells
outside the model domain, the sea cells and the river cells carry no row. The rows
are dropped later in the cells that host a connected reach
({doc}`streams-and-mover`) and in the cells of a lake bed that stays active
({doc}`lakes`). A drain does not read $D$: its elevation is $z_{\mathrm{top},n}$,
never the filled $\tilde z_n$.

(drains-conductance)=
## The conductance

When the file declares a conductance, every cell takes it as a conductance per
cell, with the floor: $C_n = \max(C^\mathrm{decl}, C_\mathrm{min})$. When it
declares none, which is the case of example 04, each drain derives its
conductance from the conductivity of its cell:

$$
C_n = \max\!\left(\frac{K_n\,a_n}{b_d},\ C_\mathrm{min}\right).
$$ (eq-drain-conductance)

The thickness $b_d$ is that of the clogging layer at the bottom of a
watercourse, decimetres to a metre. It is not the thickness of an aquifer layer.
A cell passes its own recharge when the head stands above the drain elevation by

$$
h_n - z^d_n = \frac{N_n\, a_n}{C_n} = \frac{N_n\, b_d}{K_n} .
$$ (eq-drain-excess)

The excess does not depend on the size of the cell. It depends on $K/N$, the
ratio a network calibration searches ({doc}`../downslope-distance`), and on
$b_d$. The drain is meant to be a seepage face: $K$ and the recharge decide where
the water surfaces, and the drain must not limit it. The floor $C_\mathrm{min}$
exists only for a degenerate cell, a zero conductivity for instance, whose
formula would give a conductance MODFLOW reads as no drain at all.

A zero or a negative declared value selects the derivation; it does not close
the boundary. The conductance is static unless the value is a series. A period
is written only when the declared value changes, and MODFLOW 6 reuses the last
data for the periods left out.

```toml
base_config = "step4_transient.toml"

[solver]
drain_bed_thickness_m = 0.5
```

In the code: `hk_fallback_drain_conductance`.

(drains-band)=
## The discharge band

A single drain elevation says that the land inside a cell is flat. The remedy
the USGS documents is a sub-cell discharge band, not an edit of the elevation:
the average undulation depth of a cell in UZF1, and the depth of the drain band
in the DRN package of MODFLOW 6 {cite:p}`langevin2017`. The depth can be taken
from the standard deviation of the fine land surface elevations inside a cell
{cite:p}`feinstein2020drain`. With a band of depth $\delta$, the drain sits lower
and its conductance grows:

$$
z^d_n = z_{\mathrm{top},n} - \frac{\delta}{2},
\qquad
C^{\delta}_n = C_n\,\frac{b_d}{\delta}.
$$ (eq-drain-band)

The factor is the bed thickness and not the cell area: the conductance it scales
is already $K_n a_n / b_d$, so the product is $K_n a_n / \delta$, the conductance
of a band of depth $\delta$. With the derived conductance, $b_d$ drops out. The
cell begins to discharge before the head reaches its mean elevation, and
discharges harder as the head climbs into the band. No elevation is raised and no
DEM is rewritten. MODFLOW 6 solves its own band with a smooth curve; this rule is
the piecewise equivalent, applied alike by both MODFLOW solvers.

```toml
base_config = "step4_transient.toml"

[solver]
drain_band_depth_m = 0.5
```

The seepage mask of {doc}`simulated-network` reads the band: a banded cell
discharges at $z_{\mathrm{top},n} - \delta/2$ and never climbs back to its top,
so the run keeps $\delta$ in its store for every reader.

In the code: `drain_discharge_band`.

(drains-sink-fill)=
## The other answer: no drain in the pits

{toml}`solver.sink_fill` sets the conductance to zero in every cell that sits in
a closed depression of the top. The depressions are found on the solver mesh by
a priority flood seeded on every cell water can leave the domain through, counted
on the shared faces that MODFLOW connects. Both MODFLOW solvers read the same
mask. No manual or USGS document removes a discharge boundary where a pit is
found, and the card of the key says so. The band and this key answer the same
question in opposite directions, and a file that sets both is refused.

```toml
# not checked: both keys together are refused when the file is read
base_config = "step4_transient.toml"

[solver]
sink_fill = true
drain_band_depth_m = 0.5
```

(drains-worked-cell)=
## One cell, by hand

A cell of 25 m by 25 m ($a_n = 625$ m²), $K = 10^{-7}$ m/s, and a recharge of
439 mm per year, $1.39 \times 10^{-8}$ m/s. The conductance and the head the
drain needs to pass the recharge, from {eq}`eq-drain-conductance`,
{eq}`eq-drain-excess` and {eq}`eq-drain-band`:

| Drain bed $b_d$ | Band $\delta$ | $C_n$ (m²/s) | Drain elevation | Head above it |
|---|---|---|---|---|
| 30 m | none | $2.08 \times 10^{-6}$ | $z_\mathrm{top}$ | 4.17 m |
| 1 m | none | $6.25 \times 10^{-5}$ | $z_\mathrm{top}$ | 13.9 cm |
| 0.1 m | none | $6.25 \times 10^{-4}$ | $z_\mathrm{top}$ | 1.4 cm |
| 1 m | 0.5 m | $1.25 \times 10^{-4}$ | $z_\mathrm{top} - 0.25$ m | 7.0 cm |

The first row takes a layer thickness as the bed. The drain, not the aquifer,
then limits the discharge. In the last row the head stands 7.0 cm above a drain
25 cm under the top: the cell passes its recharge 18 cm under the ground.

```{eval-rst}
.. plot:: theory/figures/exits_drain_curves.py
   :alt: Drain discharge divided by the recharge of the cell, against the head minus the model top, for the four rows of the table. The 30 m bed stays near zero, the 0.1 m bed rises steeply at the top, the banded drain starts 25 cm below the top.

   The four rows of the table as curves, from ``hk_fallback_drain_conductance``
   and ``drain_discharge_band``. The dashed line is the discharge that passes
   the recharge of the cell. The 30 m bed reaches it 4.17 m above the top, off
   the figure.
```

## Assumptions

- A drain is a seepage face: the head the drain itself needs to pass the
  recharge is small beside the thickness of the aquifer.
- The land inside a cell is flat, unless a band is declared.
- Recharge is a flux set from outside. It does not read the water table.

## Limits

- **A drain cell has one elevation.** The band is the one remedy. It applies to
  every drain cell alike and classifies nothing.
- **A declared conductance has a floor under MODFLOW 6 only.** MODFLOW-NWT takes
  it as it is.
- **The ETP is not read under MODFLOW 6 outside soil mode.** A loaded ETP is
  ignored, with a warning.

## Parameters of this page

```{hmp-params}
flow.bc.<name>.value
solver.drain_bed_thickness_m
solver.drain_conductance_floor_m2_s
solver.drain_band_depth_m
solver.sink_fill
flow.sinks_sources.recharge.negative_to_evt
flow.sinks_sources.etp.extinction_depth
flow.sinks_sources.etp.surface_offset
modflow6.process_specific.evt_extinction_depth
```

## Checked by

The tests that import the code of this page. The box is generated: a new test
appears here on the next build.

```{hmp-tested-by}
hydromodpy.solver.modflow_common.drain_conductance
hydromodpy.solver.modflow6.builders.recharge
hydromodpy.solver.modflow6.builders.boundary_conditions
hydromodpy.solver.modflow_nwt.nwt.payloads
```

## In the code

| What | Where |
|---|---|
| Recharge, EVTA, the lake mask | `hydromodpy/solver/modflow6/builders/recharge.py` |
| Drain rows | `hydromodpy/solver/modflow6/builders/boundary_conditions.py` |
| Derived conductance and band | `hydromodpy/solver/modflow_common/drain_conductance.py` |
| Drains and EVT under MODFLOW-NWT | `hydromodpy/solver/modflow_nwt/nwt/payloads/` |
