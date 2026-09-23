# 05 - Piezometry in a heterogeneous coastal aquifer

Gouville coastal strip (Normandy, EPSG:2154), **daily transient over 2016** with
**MODFLOW 6**. Two things drive the water table: a recharge that varies day to
day, and a sea level that goes up and down with the tide. The aquifer is not
uniform either: a western strip along the shore and an eastern one inland carry
their own conductivity and their own specific yield, which is what the title
calls heterogeneous.

The simulated head is put next to the measured chronicle of the BSS piezometer
`01423X0044/F4`, which stands in the western strip.

## Run

```bash
hmp run examples/projects/05_piezometry_in_a_heterogeneous_coastal_aquifer/project.toml
```

Runtime: about 20 s (366 daily stress periods over a 3.3 km² strip at 25 m).

## Data

| File | Family | Role |
|---|---|---|
| `dem/DEM_gouville_25m.tif` | dem | 25 m coastal DEM |
| `watershed_polygon/gouville_model_area.shp` | - | model area, buffered by 10 m |
| `masks/gouville_param_zones.gpkg` | geology | the two parameter zones, attribute `zone` |
| `oceanic/oceanic_custom_GOUVILLE_20160101_20161231_D.csv` | - | daily sea level 2016, m NGF |
| `piezometry/piezometry_custom_GOUVILLE_F4_...csv` | piezometry | measured head at the BSS piezometer |
| `recharge/recharge_custom_GOUVILLE_...csv` | recharge | daily reanalysis recharge, mm/day |

## The three things that make this example

**Lateral heterogeneity.** `gouville_param_zones.gpkg` holds two polygons. They
reach the parameters through the `geology` support, which is the generic way a
polygon layer becomes a per-cell zone id; nothing here is about lithology:

```toml
[domain.supports.param_zones]
kind = "geology"

[flow.param.K.field]
kind = "heterogeneous"
unit = "m/day"
field_spatial_id = "param_zones"
values = { zone_1 = 18.5, zone_2 = 95.0 }
```

**A sea level that moves.** The ocean boundary reads a chronicle instead of a
number. Every cell at or below the highest value of the series is held at the
sea level, so the shoreline cells swing with the tide:

```toml
[flow.bc.ocean.forcing]
mode = "csv"
path_file = "../../data/oceanic/oceanic_custom_GOUVILLE_20160101_20161231_D.csv"
date_column = "datetime"
value_column = "value"
units = "m"
```

**A measured chronicle to answer to.** `[[observation.points]]` samples the head
in the piezometer's cell at every timestep; `[data.piezometry]` loads what was
measured there. The two land in the `timeseries` table under different names,
so the figure is told both.

## Figures

| Figure | What it shows |
|---|---|
| `mesh_map` | solver grid |
| `parameter_map` | conductivity per cell, where the two zones are visible |
| `recharge_map` | recharge per cell |
| `piezometric_map` | water-table elevation |
| `watertable_depth_map` | water-table depth |
| `seepage_map` | seepage areas |
| `piezo_timeseries_sim_obs` | simulated head against the measured chronicle |
| `cross_section` | topography / water table / aquifer base |
| `flux_timeseries` | budget components over time |
| `water_budget` | budget per component |
| `mass_balance_error` | solver closure error per timestep |

The simulated head follows the observed one through the winter recharge, the
spring recession and the summer low, running about 0.15 m under it in the second
half of the year. The fortnightly ripple on the simulated curve in that low
period is the spring-neap cycle of the sea boundary reaching the piezometer.

## Differences with the legacy example

| Point | legacy | here |
|---|---|---|
| Solver | MODFLOW-NWT | MODFLOW 6 |
| First period | steady, on the **mean** sea level | steady, on the first day of the series |
| `Ss` | not set | 1e-5 m-1, the schema needs one for a transient run |
| Particle tracking | a `if sim_state == "steady"` branch that never ran | not carried over |

The legacy script overwrote the first day of the tide with the mean of the year
so its steady warm-up would start from a representative sea level. A CSV forcing
reads the file as it stands, so the warm-up here uses the first day instead. Over
366 periods it costs a few days of spin-up, visible as the January rise.

Three library fixes came with this port, all on the path this example is the
first to walk:

- the ocean and stream boundaries refused a head chronicle, although every
  backend already read their head as one value per stress period; the
  refusal now follows the registry, which states the capability per boundary;
- `piezo_timeseries_sim_obs` could not pair its two halves: the simulated head
  is written under `obs:<point>` and the measured one under the station of its
  data family, with a different variable name. The figure now bridges the two;
- a buffer declared as a distance (`buff_area = "10 m"`) raised before it could
  be used, because the validator normalizes it to a unitless metre count that
  the parser then refused.
