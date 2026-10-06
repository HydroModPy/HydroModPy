# Give K and Sy per geological zone

You have a map of polygons, each polygon has a code, and you want one conductivity
and one specific yield per code. Four steps get you there.

The worked case is example 05, `examples/projects/05_piezometry_in_a_heterogeneous_coastal_aquifer`.
Its map holds two polygons, `zone_1` along the shore and `zone_2` inland. Its zone names
and values belong to that coastal site. Take the structure from it, not the numbers.

The blocks below are written to be merged onto `step1_minimal.toml` of example 04, the
shortest file that runs. There K is one number:

```{hmp-resolved} flow.param.K.field.value
:config: step1_minimal.toml
```

This guide replaces that number by a table of values.

## Three names must agree

Two links make the model work. Both are plain text matches, and the file check does not
follow them, as step 4 shows.

- The support name, here `param_zones`. You write it as the table name in step 1.
  You read it again in {toml}`flow.param.K.field.field_spatial_id` in step 3.
- The zone codes, here `zone_1` and `zone_2`. They come from the code column of the
  polygon file, in step 2. You read them again as the keys of
  {toml}`flow.param.K.field.values` in step 3.

## 1. Declare the zoning

A support is a named way of cutting the domain into zones. You declare it under
{toml}`domain.supports`, and the name is yours.

```{hmp-toml}
[domain.supports.param_zones]
kind = "geology"
```

`kind = "geology"` says the zones come from the polygons you load in step 2. Nothing in
it is about lithology: any polygon layer works. Three other kinds exist,
`generated_bands`, `generated_rings` and `catchment_zones`. They are built from the model itself, not from a polygon file.

```{hmp-params}
domain.supports
domain.supports.<name>.kind
```

## 2. Load the polygons

Add `"geology"` to {toml}`data.types`, then say where the file is and which column holds
the zone code.

```{hmp-toml}
[data]
types = ["geology"]

[[data.geology.sources]]
source = "custom"
path = "../../data/masks/gouville_param_zones.gpkg"
code_field = "zone"
```

The path is the one of example 05, relative to its folder. Replace it by your file.
`code_field` is required for a vector file (Shapefile, GeoPackage, GeoJSON). The values
of that column become the zone codes.

```{hmp-params}
data.geology.sources.path
data.geology.sources.code_field
data.geology.id
```

```{tip}
Example 05 also sets {toml}`data.geology.id` to the support name. That is not needed.
The support is an alias of the loaded layer, and the run works without `id`.
```

The polygons must cover every active cell of the model. A cell that no zone covers gets
no value. The run then stops and tells you that K is zero on some active cells.

## 3. Give one value per zone

Switch K, then Sy, from `homogeneous` to `heterogeneous`.

```{hmp-toml}
[flow.param.K.field]
kind = "heterogeneous"
value__delete = true
unit = "m/day"
field_spatial_id = "param_zones"
values = { zone_1 = 18.5, zone_2 = 95.0 }

[flow.param.Sy.field]
kind = "heterogeneous"
value__delete = true
unit = "-"
field_spatial_id = "param_zones"
values = { zone_1 = 0.08, zone_2 = 0.45 }
```

These numbers are the ones of example 05. They describe a coastal strip in Normandy.
They say nothing about your site.

```{hmp-params}
flow.param.<id>.field.field_spatial_id
flow.param.<id>.field.values
flow.param.<id>.field.unit
flow.param.<id>.field.values_source
```

Each key of `values` is a zone code. Each value is in the unit of `unit`. A cell that a
zone boundary cuts gets the mean of its zones, weighted by the area each one covers.
Sy is read only by a transient run. A steady run, like step 1, never reads it. Ss can stay
homogeneous, as it does in example 05.

### Why `value__delete = true`

The two shapes of {toml}`flow.param.K.field` do not share all their keys. A homogeneous
field has `value`. A heterogeneous field has `values` and `field_spatial_id`, and refuses
`value`.

Step 1 writes `value = 5e-5`. A file that inherits step 1 through `base_config` merges
table by table, so that `value` is still there when you change `kind`. Without the line
`value__delete = true`, the check fails:

```text
$ hmp config check k.toml
Config invalid: 1 validation error(s) in k.toml:
  k.toml:3: flow.param.K.field.value: Extra inputs are not permitted (input=5e-05)
```

`value__delete = true` removes the inherited key before the file is validated. A file
that does not inherit anything has nothing to delete: write the heterogeneous shape
and leave `value` out.

## 4. Check before you run

Three checks, from the cheapest to the real run. Each one catches what the previous one
cannot.

1. `hmp config check k.toml` validates the shape of every table. It catches a missing
   `values`, an unknown key and the leftover `value` above. It does not follow the links
   between tables: a `field_spatial_id` with no matching support passes.
2. `hmp run k.toml --until resolve` stops after the supports are resolved, before any
   data is loaded. It catches a support name that no table declares:

   ```text
   Missing domain support declaration for 'nope'. Declare [domain.supports.<id>] with an explicit provider.
   ```
3. The run itself checks the zone codes when it maps the values onto the mesh. A code
   with no entry in `values` stops it:

   ```text
   step 'run_solver' failed: ValueError: Field parameter 'K' has no value for zone key(s) zone_2 of spatial support 'field_geology'. Add these keys to the parameter's value table ('values' or the file named by 'values_csv_file').
   ```

   In that message the support is named `field_geology`, the default `id` of the loaded
   layer, because that test left `id` out.

```{hmp-params}
flow.param.K.field.values
```

## Let K change with depth

```{note}
A depth factor is optional and independent of the zones. It sits in its own table under
the property, and it multiplies the value of every zone by the same factor.

The factor is evaluated at the centre of each layer, measured down from the top of the
cell. With `mode = "exponential"` it is $\exp(-d / d_c)$, where $d$ is that depth and
$d_c$ the {toml}`characteristic depth|flow.param.K.field_vertical_profile.characteristic_depth`.
It never goes below {toml}`min_factor|flow.param.K.field_vertical_profile.min_factor`
when you give one. The value you write is therefore the value at the surface.

The range of $d_c$ belongs to the site. The schema gives none.
```

```{hmp-toml}
[flow.param.K.field_vertical_profile]
mode = "exponential"
characteristic_depth = "20 m"
min_factor = 0.1
```

The numbers above are only there to make the block complete. Pick your own.
`mode = "tabulated"` reads a factor from the lists `depths` and `factors` instead, both
listed with the advanced settings.

```{hmp-params}
flow.param.<id>.field_vertical_profile.mode
flow.param.<id>.field_vertical_profile.characteristic_depth
flow.param.<id>.field_vertical_profile.min_factor
```

## Next

- The whole section, with every field and the choice of shape:
  {toml}`flow.param.<id>`.
- A model that already runs, step by step: {doc}`../get-started/staircase/index`.
- How `base_config` and `__delete` merge files: {doc}`inheritance`.
