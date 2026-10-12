# 12 - Network calibration from public services only

The Nançon at Lécousse (Ille-et-Vilaine, EPSG:2154), about 65 km², built from
one outlet coordinate and nothing else. No file ships with this example, the
DEM included: every input comes from a public French service, and one search
finds the hydraulic conductivity from the mapped stream network.

**Steady-state** flow with **MODFLOW 6**, one period over 2000-2019, and the
**hydrographic-network criterion** of Abherve et al. (2023): K alone, by
bisection, until the seepage network the water table sustains balances the
BD Topage network, permanent and intermittent reaches together. Sy is never
searched: a steady solve carries no storage, and the criterion identifies K/R.

## Run

```bash
hmp calibrate examples/projects/12_network_calibration_from_apis/project.toml --check          # every problem at once, no solve
hmp calibrate examples/projects/12_network_calibration_from_apis/project.toml --list-phases    # the one phase
hmp run examples/projects/12_network_calibration_from_apis/project.toml                        # the search, then the best run with its figures
```

Needs network access on the first launch; no service asks for a key. The
downloads land under `examples/data/` and are read from there afterwards. The
BD ALTI archives of the four departments around the outlet are the large
part, about 130 MB.

To look at the data before any solve, run the first steps as a simulation:

```bash
hmp run examples/projects/12_network_calibration_from_apis/project.toml --until load_data --set workflow.mode=simulation
```

## Data

| Family | Source | Role |
|---|---|---|
| dem | IGN Geoplateforme, BD ALTI 25 m, aggregated to 75 m (`dem_resolution`) | catchment delineation, model top, mesh at 75 m |
| hydrography | Sandre BD Topage | the mapped network the criterion is scored on, with the permanence of every reach |
| hydrometry | Hub'Eau, product `QmnJ`, station J001401001 | daily discharge at the outlet, a check of the recharge, not a target |
| recharge | Météo-France SIM2, `DRAINC_Q` | drainage averaged over the watershed; the steady solve uses its 2000-2019 mean |
| runoff | Météo-France SIM2, `RUNC_Q` | surface runoff, added to the simulated baseflow before the comparison with the gauge |

No section names a path or a bounding box. The DEM is fetched around the
outlet and aggregated to 75 m, the cell size of example 04, before the
catchment is delineated on it; every other source is asked over the
delineated watershed. The time series inherit the `[simulation.time]` window,
which carries no step: a steady run is one stress period over the whole
window, and its forcings are the means of the twenty years.
Drop `dem_resolution` to run on the 25 m pixels of BD ALTI: nine times more
cells, about a minute per steady solve, and a larger mismatch in the flat
valley bottoms that the 75 m smooths.

## The search

One phase, `steady_conductivity`. The criterion compares two descents on the
routing surface: from every simulated seepage cell down to the mapped network,
and from every mapped cell down to the simulated network. Their signed
difference, the `distance_gap` of Eq. 1, is zero where neither network
overshoots the other. The bisection sweeps seven values of K across
[1e-7, 1e-3] m/s in log space, brackets the sign change and halves the
bracket to one per cent on K: 15 steady solves here, 23 at most.

The mapped network is every reach BD Topage holds inside the catchment,
permanent and intermittent alike (`observed_network = "data.hydrography"`). No
minimal map is declared on purpose: in one state the criterion would then be
scored on the permanent reaches, and the full extent is the target here.
`run_calibration_bdtopage.toml` of example 04 shows the other reading, the
two maps as two bounds of a transient run.

The map enters by its heads, the default `observed_rasterization`: each
stream head lands on a nearby cell and the rest of the map is drawn down the
criterion's own descent, so a field ditch or a rectified reach below a head is
not counted as model error.

## Outputs

The best trial is replayed as a full run, `nancon_network_k_from_apis`, with
its figures and its exports.

- figures: `runs/nancon_network_k_from_apis/figures/`
- exports: `share/nancon_network_k_from_apis/`
- the session of the search, trial by trial: `sessions/`

The figures are the catchment card, the three networks (BD Topage, its
permanent reaches, the one the DEM delineates), the mapped heads on the mesh,
the water table and its depth, a south-north section, the budget, then the
simulated seepage against the map (overlay, confusion map, downslope
distances), and the search itself (crossing curves, bracket trace, cost
profile, progress, method card).

The exports are the catchment and the three networks as GeoPackage, the DEM
as GeoTIFF, seven GeoTIFF of the one steady state (water table elevation and
depth, seepage cells, seepage flux, simulated active network, recharge, the K
the search returned), the simulated and gauged discharge as CSV, and the
budget as CSV.

## Runtime

At 75 m the mesh holds 21 400 cells, 11 500 of them inside the catchment, the
grid of example 04. A steady solve takes a few seconds: the search closed in
15 of them in about 90 s, the promoted run took 30 s more, and the whole file
runs in about three minutes, the first DEM download apart. The bisection may
spend up to 23 solves. On the 25 m pixels, with `dem_resolution` dropped, the
same search takes about 16 minutes.
