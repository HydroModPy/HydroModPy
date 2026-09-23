# 07 - Analytical solution for streamflow recession

Synthetic 1D hillslope: 1000 m long, one 20 m cell wide, flat at 100 m over a
flat substratum at 0 m. A 33 mm/d recharge pulse fills the aquifer for 30 days,
then 960 days of recession empty it through a fixed head on the west edge.

The falling limb is compared to the **late-time solution of the non-linear
Boussinesq (1904) equation** on the log-log plane of Brutsaert and Nieber:

```
-dQ/dt = a Q^(3/2)      a = 4.804 K^(1/2) L / (f A^(3/2))
```

No external data: the domain is built by
`[geographic] source_mode = "synthetic"`.

## Run

```bash
hmp run examples/projects/07_analytical_solution_for_streamflow_recession/project.toml
```

Runtime: about 1 s (50 cells, 33 stress periods, 30 solver steps per period).

## Result

The simulated cloud lies on the analytical line to **+0.007 log10**, a 1.6%
offset on the coefficient `a`, with an exact 3/2 exponent. This is a solver
validation, not an illustration.

## Figures

| Figure | What it shows |
|---|---|
| `mesh_map` | solver grid |
| `piezometric_map` | water-table elevation |
| `cross_section` | topography / water table / aquifer base section |
| `water_budget` | budget per component |
| `mass_balance_error` | solver closure error per timestep |
| `recession_power_law` | `-dQ/dt` against `Q` in log-log, Boussinesq line and residuals |

Two of these are figures added with this port: nothing in the registry computed
`-dQ/dt` and confronted it with a power law, and nothing drew the solver's own
closure error, which the legacy script plotted from the listing file.

## Differences with the legacy example

| Point | legacy | here |
|---|---|---|
| Solver | MODFLOW-NWT | MODFLOW 6 |
| Layers | 10 | 1 |
| DEM | a 20 m raster flattened to 100 m by the script | `source_mode = "synthetic"` |
| Analysis | matplotlib inside the script | registered figure `recession_power_law` |

One layer rather than ten: MODFLOW 6 refuses a fixed head below a cell bottom,
so a stream head at the substratum has nowhere to sit inside a stack. It is
also the depth-integrated aquifer the analytical solution describes, so the
port gains from it.

The published coefficient is written for a reach drained from both banks. Here
the hillslope drains one bank only, hence `sides = 1` in
`[display.overrides.recession_power_law]`, which halves `a`. Without it the
simulated cloud sits exactly a factor two below the line.
