# Step 2: the mapped network and the gauge

Step 2 adds two pieces of data, read from local files: the mapped river network and the
discharge gauge at the outlet. The run is still steady. The point is the comparison: the
cells where the simulated water table reaches the surface should lie where the map draws a
stream. The figures show where they agree and how far each simulated cell is from the map.

## The file

```{hmp-step} step2_local_data.toml
```

## Run it

```bash
hmp run step2_local_data.toml
```

The network is the GeoPackage `nancon_stream_network.gpkg`, which `hmp example add` put in
`data/hydrography/`. The gauge is the `NANCON` station of `data/hydrometry/`, a daily record
from 1982 to 2022. Nothing is downloaded.

## What you get

{toml}`display.figures` is a list, so step 2 replaces step 1's list. Four figures:

| Figure | What it shows |
|---|---|
| `watershed_id_card` | As in step 1 |
| `hydrographic_network_reference` | The mapped network alone |
| `seepage_network_confusion_map` | Three classes: *valid* where the two networks share a cell, *excess* where only the model has a stream, *missing* where only the map has one |
| `downslope_distance_map` | How far each simulated cell must descend before it reaches the mapped network, in four classes: 0 to 75 m, 75 to 500 m, 500 to 1000 m, and more than 1000 m |

Step 1's three exports are inherited. `[[export__append]]` adds a fourth: the mapped
network, as a GeoPackage, in `share/nancon_step2_local/`.

## Key fields

```{hmp-params}
data.types
data.hydrography.sources.path
simulation.results.derived.release_flux
simulation.results.budget.spatial_fields
```

Next: {doc}`step3`, the same data from the APIs, or {doc}`step4`, the transient run.
