# Give K and Sy per geological zone

```{hmp-task}
Task
: Give one hydraulic conductivity (K) and one specific yield (Sy) to each zone of a map.

Time
: Twenty minutes. A steady run of example 04 with zones takes under a minute on two cores.

Needs
: A model that runs, and a polygon or raster file of the zones, or a rule that cuts the domain into zones.

Gives
: A model whose cells take the value of their zone, and a map of K to check it.
```

You have a way of cutting the model domain into zones, and you want one hydraulic
conductivity (K) and one specific yield (Sy) per zone. After these steps each cell takes
the value of its zone. A cell that a zone boundary cuts takes the mean of its zones,
weighted by the share of the cell each one covers.

The worked case is example 04, `examples/projects/04_streamflow_intermittence_in_transient`.
The zone codes, the file name and the values below are placeholders for your own site.
Take the structure from them, not the numbers.

## What you need first

- A model that runs. The blocks are written to be added to
  `step4_transient.toml` of example 04, a transient file, because Sy is read only by a
  transient run. A steady run, like step 1, never reads it. In step 4, K is one number:

  ```{hmp-resolved} flow.param.K.field.value
  :config: step4_transient.toml
  ```

  This guide replaces that number by a table of values.
- For zones read from a map: a polygon file (Shapefile, GeoPackage or GeoJSON) with one
  column that holds the zone code, and polygons that cover every active cell of the model.
  A GeoTIFF of numeric classes is also accepted.
- For zones that need no file: nothing. See {ref}`zones-without-a-file`.

## Choose where the zones come from

A zoning is called a support. You declare each one under {toml}`domain.supports`, with a
name you choose and a {toml}`kind|domain.supports.<name>.kind`.

| kind | The zones come from | The keys of `values` are |
| --- | --- | --- |
| `geology` | a polygon or raster file you load, or the BRGM map | the codes found in the file |
| `generated_bands` | break coordinates along x or y | the labels you write |
| `generated_rings` | radii around a centre | the labels you write |
| `catchment_zones` | the zones built when the catchment is delineated | `core`, `buffer`, `domain` |

If every parameter is homogeneous, you declare no support. A support that no parameter
names is not built. Nothing is inferred: a heterogeneous parameter whose support you did
not declare stops the run (see {ref}`k-per-zone-problems`).

Mixing is allowed. {toml}`domain.supports` can hold a `geology` support for K and a
`generated_bands` support for Sy. Each heterogeneous parameter points to the one it needs.

```{hmp-params}
domain.supports
domain.supports.<name>.kind
```

## Two names must agree

Two links make the model work. Both are plain text matches, and the file check does not
follow them, as step 4 shows.

- The support name, here `lithology`. You write it as the table name in step 1.
  You read it again in {toml}`flow.param.K.field.field_spatial_id` in step 3.
- The zone codes, here `granite` and `schist`. They come from the code column of the
  polygon file, in step 2. You read them again as the keys of
  {toml}`flow.param.K.field.values` in step 3. A code is read as text, with surrounding
  spaces removed. Case counts: `Granite` is not `granite`.

## 1. Declare the zoning

```toml
[domain.supports.lithology]
kind = "geology"
```

`kind = "geology"` says the zones come from the geology data you load in step 2. Nothing
in it is about lithology: any polygon layer works.

## 2. Load the polygons

Say where the file is and which column holds the zone code.

```toml
[[data.geology.sources]]
source = "custom"
path = "geology/lithology.gpkg"
code_field = "unit"
```

Replace `path` by your file. A path with a folder in it is read from the folder of the
config file. A bare file name is looked up there first, then in the `data/geology` folder
of the workspace. `code_field` is required for a vector file. The values of that column
become the zone codes. Polygons with an empty code are dropped.

You do not need to list `"geology"` in {toml}`data.types`: a `geology` support asks for
it. Without a {toml}`data.geology.sources` section, the run loads the BRGM 1:1M national
map, whose codes come from its `CODE_LEG` legend.

```{hmp-params}
data.geology.sources.path
data.geology.sources.code_field
data.geology.id
```

```{tip}
{toml}`data.geology.id` is the name of the loaded layer. You do not need to set it: the
support is an alias of that layer under the name you chose in step 1.
```

The polygons must cover every active cell of the model. A cell that no zone covers gets
no value. The run then stops and tells you that K is zero on some active cells.

## 3. Give one value per zone

Switch K, then Sy, from `homogeneous` to `heterogeneous`.

```toml
[flow.param.K.field]
kind = "heterogeneous"
value__delete = true
unit = "m/day"
field_spatial_id = "lithology"
values = { granite = 4.0, schist = 0.9 }

[flow.param.Sy.field]
kind = "heterogeneous"
value__delete = true
unit = "-"
field_spatial_id = "lithology"
values = { granite = 0.03, schist = 0.06 }
```

Each key of `values` is a zone code. Each value is in the unit of `unit`. Step 4 states K
in m/s and your table may use m/day: the unit is read per parameter.

```{hmp-params}
flow.param.<id>.field.field_spatial_id
flow.param.<id>.field.values
flow.param.<id>.field.unit
```

The third storage parameter can stay homogeneous. Step 4 gives Ss one number:

```{hmp-toml}
:file: step4_transient.toml
:tables: flow.param.Ss.field
```

`value__delete = true` removes the `value` that step 4 inherits from step 1: a
heterogeneous field refuses `value`, and a table written in a file merges with the
inherited one key by key. A file that inherits nothing writes the heterogeneous shape and
leaves `value` out. The merge rules are in {doc}`inheritance`.

### Keep the values in a table file

For many zones, a CSV file is easier to read than an inline table. It has one column of
zone codes and one column of values.

```toml
[flow.param.K.field]
kind = "heterogeneous"
value__delete = true
unit = "m/day"
field_spatial_id = "lithology"
values_source = "csv"
values_csv_file = "k_by_unit.csv"
```

The file is read from the folder of the config file. The columns are called `zone_key`
and `value` unless you name others with {toml}`flow.param.K.field.csv_key_column` and
{toml}`flow.param.K.field.csv_value_column`.

```{hmp-params}
flow.param.<id>.field.values_source
flow.param.<id>.field.values_csv_file
```

(zones-without-a-file)=
## Zones that need no file

Three kinds of support are built from the model itself. They are useful for a test case,
a benchmark or a first look before the geology is ready. You write the labels yourself,
and they are the keys of `values`.

`generated_bands` cuts the domain along one axis. Breaks are fractions of the domain
extent, strictly between 0 and 1. Two breaks make three bands, so three labels.

```toml
[domain.supports.west_east]
kind = "generated_bands"
axis = "x"
breaks = [0.3, 0.7]
labels = ["west", "middle", "east"]

[flow.param.K.field]
kind = "heterogeneous"
value__delete = true
unit = "m/day"
field_spatial_id = "west_east"
values = { west = 8.0, middle = 2.0, east = 0.5 }
```

`generated_rings` cuts the domain in concentric rings around a centre, by default the
middle of the domain. Radii are fractions of the largest circle that fits in the domain
around that centre. Two radii make three zones.

```toml
[domain.supports.rings]
kind = "generated_rings"
radii = [0.4, 0.8]
labels = ["inner", "middle", "outer"]
```

`catchment_zones` reuses the zones the model builds when it delineates the catchment. They
are named `core` for the delineated catchment, `buffer` for the ring that
{toml}`geographic.catchment.buff_area` adds around it, and `domain` for the rest of the
domain box. When {toml}`geographic.catchment.catch_def` is `dem`, the whole domain is one
zone named `uniform`. Use it to give the buffer a different K from the catchment.

```toml
[domain.supports.catchment]
kind = "catchment_zones"

[flow.param.K.field]
kind = "heterogeneous"
value__delete = true
unit = "m/day"
field_spatial_id = "catchment"
values = { core = 2.0, buffer = 2.0, domain = 2.0 }
```

```{hmp-params}
domain.supports.<name>.axis
domain.supports.<name>.breaks
domain.supports.<name>.labels
domain.supports.<name>.radii
domain.supports.<name>.source_zone_id
```

Break and radius coordinates can also be absolute lengths, in the advanced setting
{toml}`domain.supports.<name>.coordinate_mode`. The ring centre is
{toml}`center_x|domain.supports.<name>.center_x` and
{toml}`center_y|domain.supports.<name>.center_y`.

## 4. Check before you run

Four checks, from the cheapest to the real run. Each one catches what the previous one
cannot.

1. `hmp config check k.toml` validates the shape of every table. It catches a missing
   `values`, an unknown key, a `labels` list of the wrong length and the leftover `value`
   above. It does not follow the links between tables: a `field_spatial_id` with no
   matching support passes.
2. `hmp run k.toml --until resolve` stops after the supports are resolved, before any
   data is loaded. It catches a support name that no table declares.
3. `hmp run k.toml` loads the polygons, maps the values onto the mesh and checks the zone
   codes. It catches a code with no entry in `values`, and a model domain that the
   polygons do not cover.
4. Look at the result. `hmp viz show @last parameter_map` draws K on the mesh, layer by
   layer from the top. The zones must land where the geology says they should.
   `hmp viz show @last parameter_section` cuts the aquifer along a line and colours K,
   Sy and Ss. Both figures read the fields the run stored.

Example 04 ships no geology polygons, so the figure below comes from the three bands of
{ref}`zones-without-a-file`, west, middle and east, at 8, 2 and 0.5 m/day.
{download}`The file of that run <recipes/model/guide_k_zones.toml>` is step 1 of example 04 with
those bands; it runs in under a minute.

```{figure} /_static/figures/guides/k-per-zone/parameter_map.webp
:alt: Map of K over the Nançon model in three vertical bands, high in the west, low in the east.

`parameter_map` of the three bands. Each cell takes the value of its band.
```

(k-per-zone-problems)=
## What can go wrong

Names in angle brackets stand for your values.

| Symptom | Cause | Fix |
|---|---|---|
| `Missing domain support declaration for 'lithology'. Declare [domain.supports.<id>] with an explicit provider.` at the resolve step | {toml}`flow.param.K.field.field_spatial_id` names a support that no table declares. | Declare `[domain.supports.lithology]` with the same name. |
| `'code_field' is required for custom vector geology source (lithology.gpkg). Set it in [[data.geology.sources]] to the column containing geology codes.` | A polygon file read without `code_field`. | Name the column of the codes. |
| `Column 'unit' not found in /path/to/lithology.gpkg. Available: ['id', 'name', 'geometry']` | `code_field` is not a column of the file. | Take a name from the list. |
| `Field parameter 'K' has no value for zone key(s) schist of spatial support 'field_geology'. Add these keys to the parameter's value table ('values' or the file named by 'values_csv_file').` | A zone code with no entry in `values`. For a `geology` support, the message names the loaded layer ({toml}`data.geology.id`, `field_geology` by default), not your support. | Add the code to `values`. |
| A zone takes a value you did not write, and nothing is reported | A key of `values` that matches no zone is ignored: a stale or misspelt key never raises an error. | Compare the keys of `values` with the codes of the file. |
| `K is zero, negative or not finite on <n> of <m> active cell(s) (<n> zero, 0 not finite). K is heterogeneous on spatial support 'lithology'. A cell that no zone of this support covers gets no value, ...` when the solver inputs are built | The polygons leave active cells uncovered. | Extend the polygons, or load a second source that fills the gap. |

## Next

- Let K change with depth, inside every zone: {doc}`depth-and-substratum`.
- The whole section, with every field and the choice of shape:
  {toml}`flow.param.<id>`.
- Search the zone values with a calibration: each zone is one target, named like `K.granite`.
  `hmp config targets k.toml` lists them. See {doc}`calibrate`.
- Load your own polygon or raster files: {doc}`use-your-own-files`.
- A model that already runs, step by step: {doc}`../get-started/staircase/index`.
- How `base_config` and `__delete` merge files: {doc}`inheritance`.
