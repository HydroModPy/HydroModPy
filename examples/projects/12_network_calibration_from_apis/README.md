# 12 - Network calibration from public services only

The Nançon at Lécousse (Ille-et-Vilaine), about 65 km², from one outlet
coordinate and nothing else. Every input comes from a public French service,
the DEM included. Steady state with MODFLOW 6 over 2000-2019, then K is found
by bisection where the simulated seepage network balances the BD Topage
network, permanent and intermittent reaches together (Abherve et al., 2023).
Sy is never searched: a steady solve carries no storage, and the criterion
identifies K/R.

## Run

```bash
hmp calibrate examples/projects/12_network_calibration_from_apis/project.toml --check
hmp run examples/projects/12_network_calibration_from_apis/project.toml
```

Needs network access on the first launch; no service asks for a key. The
downloads land under `examples/data/`. The BD ALTI archives of the four
departments around the outlet are the large part, about 130 MB.

## Data

| Family | Source | Role |
|---|---|---|
| dem | IGN BD ALTI 25 m, aggregated to 75 m by `dem_resolution` | delineation, model top, mesh |
| hydrography | Sandre BD Topage | the mapped network the criterion is scored on |
| hydrometry | Hub'Eau, station J001401001 | daily discharge at the outlet, exported for comparison |
| recharge | Météo-France SIM2 | drainage averaged over the watershed, then over the twenty years |
| runoff | Météo-France SIM2 | surface runoff, added to the simulated baseflow |

The time series inherit the `[simulation.time]` window. A steady run is one
stress period over it, so the window carries no step.

## Outputs

The best trial is replayed as the run `nancon_network_k_from_apis`, with six
figures in `runs/<run>/figures/`: the catchment card, the BD Topage map with
its permanence, the water table depth, the confusion map and the downslope
distances of the simulated network against the map, and the calibration card.

`share/<run>/` holds the catchment and the BD Topage network as GeoPackage,
the water table depth, the seepage cells and the seepage flux as GeoTIFF, the
simulated and gauged discharge as CSV, and the budget as CSV. Anything else
the run stores, `hmp export <run> --list` names it.

## Runtime

21 400 cells at 75 m, the grid of example 04. About 15 steady solves of a few
seconds each: three minutes in all, the first DEM download apart.
