# Step 5: every export

Step 5 does not change the model. It is step 4 with its results written out in every format
HydroModPy can export. The file drops the inherited exports with `export__delete = true`
and states its own list, one `[[export]]` block per request. A block says *what*
(`variables`), *when* (`time` or `period`), and where and how (`format`, `file`, `crs`).

## The file

```{hmp-step} step5_export.toml
```

## Run it

```bash
hmp run step5_export.toml
hmp export nancon_step5_export --list
```

`--list` prints what the run can export, by kind, and writes nothing.

## What you get

Eleven export blocks, in `share/nancon_step5_export/`. The format follows the data unless the
block says otherwise: a vector layer is a GeoPackage, a series or a table is a CSV, and a
field at one instant is a GeoTIFF.

| What | When | Format |
|---|---|---|
| the catchment and the mapped network | | GeoPackage |
| the catchment | | Shapefile |
| the DEM the catchment was cut from | | GeoTIFF |
| `head`, `watertable_depth`, `seepage_mask` | 15 October 2002 | one GeoTIFF per variable |
| the simulated active network, as mesh cells | 15 October 2002 | GeoPackage |
| `head`, `watertable_depth` | the whole record | NetCDF, `watertable_2000_2002.nc` |
| `discharge`, `discharge_obs` | 2001 and 2002 | CSV |
| the water budget, monthly | | CSV |
| `watertable_depth` | 15 October 2002 | GeoTIFF reprojected to `EPSG:4326`, for a web map |
| `head` | 15 October 2002 | VTU, for ParaView |
| everything | | a portable archive of the run (`package`) |

Eight figures, drawn from the same data: `watershed_id_card`, `flux_timeseries`,
`hydrograph_sim_obs`, `watertable_depth_map`, `seepage_map`, `seepage_network_confusion_map`,
`downslope_distance_map` and `flow_persistence_map`.

Once a run exists you can also ask for files without editing the TOML, for example
`hmp export nancon_step5_export head watertable_depth --time 2002-10-15`.

## Key fields

```{hmp-params}
export.variables
export.time
export.format
export.file
```

The other keys of a block are {toml}`export.period`, {toml}`export.crs` and
{toml}`export.folder`.

Next: {doc}`step6`, a daily run with a soil reservoir.
