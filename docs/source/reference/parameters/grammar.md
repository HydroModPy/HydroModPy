# The grammar of a HydroModPy file

One TOML file describes a run. Its sections are listed in {doc}`index`; this page gives the
rules they all share: tables, inheritance, quantities, dates, paths, free keys and
profiles. The rules are written by hand. Every key this page cites and every TOML block it
shows is checked against the models of the code.

## Tables and arrays of tables

A section is a TOML table: `[flow]`. A table can sit inside another one: the header
`[flow.param.K.field]` opens the table `field` of the table `K` of `param`. You do not
need to write `[flow]` first.

A request that you may repeat is an **array of tables**, written with double brackets. Each
`[[export]]` block is one export, in the order of the file. The same form holds the
sources of a data variable, the processes of a simulation, the observation points, the
stages of a calibration and its objective blocks.

```{hmp-toml}
[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[[export]]
variables = "watershed"

[[export]]
variables = ["watertable_depth", "seepage_mask"]
time = "last"
```

Three rules hold for the whole file.

- A file has only the top-level sections listed in {doc}`index`. A name that is not one of them is refused:
  `Unknown top-level TOML section(s): flows`.
- A key that the table does not know is refused, and the message names the table:
  `Unknown TOML key(s) in [flow]: flow_regme`.
- Two things are required in every file: a `[site]` with {toml}`site.name` when the file
  models a real catchment, and `[geographic]`. In its standard mode, `[geographic]` needs
  `[geographic.catchment]` with {toml}`geographic.catchment.kind`, and
  `kind = "dem"` needs {toml}`geographic.catchment.dem_init_path`. With these keys,
  `hmp config check` accepts the file. `[workflow]` can be left out: the sections of the file
  say what it does. A file never writes the project root: it is the folder that holds
  `project.toml`.

(base-config)=

## `base_config`: start from another file

A file can inherit every table of another one. It writes only what changes.

```{hmp-toml}
:caption: a child file, five lines
base_config = "base.toml"

[simulation]
name = "nancon_daily"

[simulation.time]
step_value = "1 day"
```

`base_config` is a top-level key, so it goes before the first table header. Its value is a
path, read from the folder of the file that holds it. An absolute path works, and `~` is
expanded. The parent can have its own `base_config`: the chain is read from the oldest
ancestor down, and a loop stops with `Detected circular base_config chain`. Once the
files are merged, `base_config` is gone, and the merged result is what the schema
validates.

`hmp run` and `hmp calibrate` add two more layers on top of the chain, in this order: files given with
`--overlay`, then values given with `--set`. Environment variables named `HMP_SET_*` come
last.

```bash
hmp run run.toml --overlay daily.toml
hmp run run.toml --set simulation.name=my_run
hmp calibrate calibration.toml --set calibration.seed=7 --case calage_seed7
HMP_SET_simulation__name=my_run hmp run run.toml
```

A `--set` value is read as TOML when it can be, and as a plain string otherwise: `200` is
a number and `my_run` is a string. In an environment variable name, two underscores stand
for a dot and the case is the case of the key: `HMP_SET_flow__param__K__field__value=3e-5`
sets `flow.param.K.field.value`.

Each file, each overlay and each `--set` value is read under today's key names before the
merge. So a key an overlay writes under an old name wins over the same key its base writes
under the new name. A warning names the file that holds the old key, and
`hmp doctor --fix-config <file>` rewrites that file and the files it inherits, then prints
what changed in each one. It writes nothing when a rewrite of the files one by one would
change what they read together, and it names those keys.

## Merging: tables, lists, `__append`, `__merge`, `__delete`

The same merge applies to the files of the chain, to overlays and to `--set` values. A table
merges key by key. Any other value replaces the parent's value, and this holds for lists too,
whatever their lengths. Three suffixes on a key change this rule for that key.

| The child writes | The result holds |
|---|---|
| a table the parent also has | both tables, merged key by key down to the leaves |
| a number, a string, a boolean | the child's value |
| a list of values, `figures = [...]` | the child's list, which **replaces** the parent's |
| `figures__append = [...]` | the parent's list, then the child's items |
| `key__delete = true` | the parent's key or table removed, with all that is under it |
| `[[x]]` blocks | the child's blocks, which **replace** the parent's, whatever their number |
| `[[x__append]]` | the parent's blocks, then the child's |
| `[[x__merge]]` | each block merged with the parent's block of the same identity, the other blocks as they are |

Inside one table, the merge runs in three passes: the deletions, then the keys the file
writes, then the merges and the appends. A key that is deleted and written again in the same
table starts from nothing: this is why `sources__delete = true`, followed by a new list of
sources, does not inherit the old keys. `key__delete` needs the literal `true`, `key__append`
needs a list, and `key__merge` needs an inherited list of tables and is refused next to the
plain `key`. No key of the schema holds two underscores, so a suffix never collides with a
key. A name you choose yourself must not end with one of the three suffixes. To see the file
a chain resolves to, before validation, run `hmp config resolve <file>`.

```{hmp-toml}
:caption: five rules in one file
base_config = "base.toml"

[flow.param.K.field]
value = 1e-4                    # kind and unit are inherited

[display]
figures__append = ["duration_curve"]

[[export__append]]
variables = "watershed_dem"

[data.hydrography]
sources__delete = true          # drop the inherited list

[[data.hydrography.sources]]
source = "bdtopage"
```

`__merge` pairs blocks by their identity, which is the first of `id`, `name` and `source` that
every block on both sides holds. So {toml}`simulation.process` and {toml}`observation.points`
pair by `id`, {toml}`calibration.phases` and {toml}`calibration.objective_blocks` by `name`, and
the `sources` of a data variable by `source`. A parent can insert a block at its head, and each
child still reaches the block it names. The child writes only the blocks it changes, and the
list keeps the order of the parent.

```{hmp-toml}
:caption: one block of an inherited list changes
base_config = "step1_minimal.toml"

[[simulation.process__merge]]
id = "flow_main"
solvers = ["modflow_nwt"]
```

Four cases are refused, and the message says what to write.

- A block whose identity the parent does not hold. Correct it, or add the block with
  `[[x__append]]`.
- Two blocks of one side with the same identity. Give each one its own, or replace the list
  with `[[x]]`.
- Blocks with no identity, as in {toml}`export` and {toml}`mesh.refinement_zone`. Write the whole
  list with `[[x]]`, or add blocks with `[[x__append]]`. Position does not pair them, because
  two lists of the same length can still be two different lists. The one exception is a list of
  one block on each side, since there is only one way to pair them.
- `[[x__merge]]` next to a plain `[[x]]` in one file.

Two traps come from inheritance, not from the merge itself.

- **A list that other keys depend on.** In `[flow]`, every table of `param` must be named in
  {toml}`flow.param_list`. A child that adds `[flow.param.Ss.field]` and does not touch the
  inherited list is refused: `flow.param contains ids not declared in flow.param_list: Ss`.
  Write `param_list__append = ["Ss"]`. Or leave `param_list` out of every file: it is then
  taken from the tables.
- **A table that changes shape.** `value` belongs to `kind = "homogeneous"`, and `values` to
  `"heterogeneous"`. A child that switches the kind must remove the old key with
  `value__delete = true`, or the file is refused with `Extra inputs are not permitted`.

An empty string is not a value: a key written `""` is dropped when the file is read, as if
it were absent, and the default of the model applies.

## Quantities and units

Many fields take a length, a duration or a rate. The `form` of a field says how: `number or
"<n> m"` reads a bare number, or a string made of a number, a space and a unit. Write the
string in quotes: `snap_dist = "150 m"`. Unquoted, `150 m` is not valid TOML.

The registry counts 87 fields typed as a quantity. They come in five kinds. In each, a
bare number is in the unit shown, and a string needs a unit: `"150"` is refused.

| Kind of field | A bare number is in | Strings read | Examples |
|---|---|---|---|
| a length | meters | `"150 m"`, `"0.15 km"`, `"15000 cm"`, converted to meters | {toml}`geographic.catchment.snap_dist`, {toml}`domain.depth_model.thickness` |
| a length in millimeters | mm | `"150 mm"`, `"15 cm"`, `"0.15 m"` | {toml}`flow.sinks_sources.recharge.soil.ru` |
| a duration in days | days | `"5 days"`, `"1 week"`, `"12 h"` | {toml}`flow.sinks_sources.recharge.soil.transit_time` |
| a volumetric flow | m3/s | `"36 L/s"`, `"10 m^3/h"` | {toml}`flow.sinks_sources.wells.<name>.forcing.value` |
| a flux density | m/s | `"2 mm/day"`, `"500 mm/yr"` | {toml}`flow.ic.h.rate` |

For a volumetric flow, write `m^3/s` or `m³/s`. The shorthand `m3/s`, which the form of
the field shows, is refused today.

The value of a flow parameter, {toml}`flow.param.K.field.value`, works another way. Its
unit sits in the sibling key {toml}`flow.param.K.field.unit`, or inside the string:
`unit = "m/day"` with `value = 4.3`, or `value = "4.3 m/day"` alone. Both at once are
accepted when they agree, and refused when they differ. Left out, the unit is the SI one of
the name: `m/s` for `K`, `-` for `Sy`, `m-1` for `Ss`, and `-` for any other name. The
accepted units are `-`, `m/s`, `m/day`, `m/h`, `cm/s`, `cm/day`, `cm/h`, `mm/s`,
`mm/day`, `mm/h`, `m-1` and `cm-1`. The validated file keeps the value as written, with its
unit. It is converted to SI when the parameter is built: `0.36` in `m/h` becomes `1e-4`
in `m/s`.

```{hmp-toml}
:caption: quantities, validated on step 1
[geographic.catchment]
snap_dist = "150 m"
buff_area = "10%"

[domain.depth_model]
thickness = "30.0 m"

[flow.param.K.field]
unit__delete = true
value = "4.3 m/day"
```

Three more cases. {toml}`geographic.catchment.buff_area` is the only field that reads a
percentage: `"10%"` enlarges the catchment area by 10 %, `"500 m"` or `"2 km"`
is a distance, and `"10% of sqrt(area)"` is the rule of version 1 written out. A bare number
still reads as that rule and warns, and `hmp doctor --fix-config` rewrites it in the explicit
form with the same distance. Some
keys carry the unit in a sibling key, as in {toml}`flow.sinks_sources.lakes.<name>.bedleak_unit`.
And a field that takes a list of values takes one value too: `variables = "budget"` and
`variables = ["head", "budget"]` are both read by {toml}`export.variables`.

### A bare number keeps the unit it always had

A bare number has no unit of its own. It is read in the unit its table has always read, and
no release changes that meaning. To write another unit, write a string with the unit, or the
sibling `unit` key where the table has one. The table gives the unit by section.

| Section | A bare number is in |
|---|---|
| `[geographic.catchment]` lengths (`snap_dist`, `dem_resolution`) | meters |
| `[domain.depth_model]` thicknesses and depths | meters |
| `[data.recharge]` and `[flow.sinks_sources.recharge]` values | mm/day |
| `[flow.sinks_sources.etp]` values | mm/day, as its `units` key says |
| `[flow.sinks_sources.recharge.soil]` depths | millimeters |
| `[flow.sinks_sources.wells]` rates and forcings | m3/s |
| `[flow.sinks_sources.lakes]` and `[flow.sinks_sources.sfr]` rates | m3/s |
| a head boundary `value` in `[flow.bc]` | meters |
| a flux boundary forcing in `[flow.bc]` | m/s |
| `[flow.param.<id>.field]` value | the unit of the name (`K` in m/s, `Ss` in 1/m, `Sy` without unit), or its `unit` key |
| `[solver]` depths and thicknesses (`drain_band_depth_m`, `drain_bed_thickness_m`) | meters |
| `[transport.modflow6prt.parameters]` times | days |
| `[transport.modflow6gwt]` and `[transport.mt3dms]` rates and diffusion | seconds, the clock of the two solvers |
| `[simulation.time]` `step_value` | the `step_unit` beside it |
| `[calibration.parameters]` bounds | the unit the target declares |

The `unit` of each field in the generated reference repeats this when the code states it. A
field whose unit depends on the model, such as the closure criteria of the solvers, has no
`unit` in the reference, and its description says what it reads.

## Dates and durations

The simulated window is {toml}`simulation.time.start_datetime` and
{toml}`simulation.time.end_datetime`, with a step. Both dates are required once the table
exists. **The end date is inclusive**: `end_datetime = "2002-12-31"` ends the run at the
end of that day. The window must end on a step boundary, and the run refuses it
otherwise: a monthly step cannot end on the 15th.

```{hmp-toml}
:caption: three years at a monthly step: 36 stress periods
[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"
step_value = "1 month"
```

{toml}`simulation.time.step_value` is a positive whole number with a unit among `hour`,
`day`, `month` and `year`: `"1 month"`, `"1 day"`, `"6 hour"`. A bare number needs
`step_unit` beside it. A unit that disagrees with `step_unit` is refused, and so is
`"1 week"`.

Write dates as quoted strings, `"2002-10-15"`. A TOML date without quotes is read by some
fields and refused by others: {toml}`simulation.time.start_datetime` accepts it, and the
`date_start` of the data tables does not.

An instant is a date, `"first"` or `"last"`. A date selects the stress period that holds
it, so the same date names the same month on a monthly or a daily run. The key
{toml}`export.time` also takes a list of instants.

A window has two spellings. A two-item list, `["2001-01-01", "2002-12-31"]`, is the form
of {toml}`export.period`. A table with `start` and `end` is the form of
{toml}`metrics.window` and {toml}`calibration.scoring_window`. The data tables take a
`date_start` and a `date_end`; left out, they use the simulated window.

```{hmp-toml}
:caption: instants and windows, validated on step 4
[display]
time = "2002-10-15"

[[export__append]]
variables = "discharge"
period = ["2001-01-01", "2002-12-31"]

[[export__append]]
variables = "watertable_depth"
time = "last"
```

## Paths

A path in a file is read from **the project root**, the folder that holds `project.toml`
at or above the file. Outside a project, it is the folder of the oldest file of the
`base_config` chain. It is not read from the folder of the file that wrote it: a file in
`plan/<hash>/` or in `runs/<case>/` names the same `dem_init_path` as `project.toml` does. The
loader merges the files first, then resolves the paths, so a path written in a parent, in an
`--overlay` file or in a `--set` value is read from the same root.

| Written as | Read from |
|---|---|
| `"dem.tif"`, a bare name, in a field that is an input file | the project root; if the file is not there, `<workspace>/data/<role>/`, then `<workspace>/data/` |
| `"data/dem.tif"` or `"../dem.tif"` | the project root |
| `"/data/dem.tif"` or `"~/dem.tif"` | as written, with `~` expanded |
| the value of `base_config` | the folder of the file that holds it |
| {toml}`export.folder` | the `exports/` folder of the run, `runs/<name>/exports/`; an absolute folder is refused |
| a relative {toml}`export.file` | the `folder` of the same block |

The `<role>` is the kind of data: `dem`, `hydrography`, and so on. The workspace is found in
this order: `[workspace]` with `root` or `data_dir`, the environment variable
`HMP_WORKSPACE`, the layout `<workspace>/projects/<name>/project.toml` beside a `data/`
folder, and last the project folder itself. This is why a file can write
`dem_init_path = "dem.tif"` and not a full path: the file sits in the data folder of the
workspace.

## Free keys: `<id>` and `<name>`

Some tables are keyed by a name. The reference writes the name as `<id>` or `<name>`, and
you write the name itself. A key like this is free, or it is drawn from a list, or it must
match a name written elsewhere.

| Table | The key is | It must match |
|---|---|---|
| {toml}`flow.param.<id>` | a parameter name: `K`, `Sy`, `Ss` | an entry of {toml}`flow.param_list`; `field.id`, if written, is the same name |
| {toml}`flow.bc.<name>` | one of `drainage`, `ocean`, `stream`, `north_side`, `south_side`, `east_side`, `west_side` | nothing: the table turns the boundary on, even empty, and `enabled = false` in it turns it off |
| {toml}`flow.sinks_sources.wells.<name>`, `lakes`, `sfr`, `flow_barriers` | a name you choose | for a lake, the `lake_id` of a calibration output with `support = "lake"` |
| {toml}`domain.supports.<name>` | a name you choose | `field_spatial_id` of the parameters that use it, and `data.geology.id` for a geology support |
| {toml}`calibration.parameters.<name>` | `K`, `Sy`, `Ss`, `thickness` or `drainage` resolve to their target; any other name needs `path` | `parameters` of a calibration phase |
| {toml}`calibration.outputs.<name>` | a name you choose | `uses_outputs` of an objective block, `outputs` of a phase |
| `[display.overrides.<figure>]`, see {toml}`display.overrides` | the name of a registered figure | `hmp viz list` prints the names; another name is refused with the list |

One name can appear in three places. Here a support called `geology_zones` is declared,
filled from a geology file, and used by K:

```{hmp-toml}
:caption: one name in three places, validated on step 1
[domain.supports.geology_zones]
kind = "geology"

[data]
types = ["geology"]

[data.geology]
id = "geology_zones"

[[data.geology.sources]]
source = "custom"
path = "geology.gpkg"
code_field = "zone"

[flow.param.K.field]
kind = "heterogeneous"
unit = "m/s"
field_spatial_id = "geology_zones"
values = { zone_1 = 1e-5, zone_2 = 3e-4 }
value__delete = true
```

The links of this site accept both spellings: `flow.param.K.field.value` and
`flow.param.<id>.field.value` lead to the same card. {doc}`explorer` shows every key of
the file as a tree.

## One rule switches a boundary on

A boundary, a sink or a source is active when its table is declared, and `enabled = false`
keeps the table and switches it off. There is no list of what is active. An empty table is
enough when nothing is left to say:

```toml
[flow.bc.drainage]               # drains at the top, conductance from K

[flow.sinks_sources.recharge]    # the rate comes from [data.recharge]

[flow.bc.ocean]
value = 0.0
enabled = false                  # kept for later, builds nothing
```

The tables are {toml}`flow.bc.<name>`, `[flow.sinks_sources.recharge]`, `[flow.sinks_sources.etp]`,
and one table per entry of `wells`, `lakes`, `sfr` and `flow_barriers`.

## Profiles

Every key has a profile: `user`, `dev` or `expert`. Of the 1760 keys of the registry, 1058 are
`user`, 607 are `dev` and 95 are `expert`. The profile says who needs the key. It does not
forbid anything: a file that writes a `dev` key, such as
{toml}`simulation.time.substeps_per_period`, is valid. The profile decides what the
reference shows by default, and what the terminal prints:

```bash
hmp config template --profile user
hmp config schema --section flow --profile dev
```

One case needs care. A choice can require keys of a higher profile: `kind = "tabulated"`
of {toml}`flow.param.<id>.field_vertical_profile.kind` needs `depths` and `factors`, and
both are tagged `dev`. The `profile` key of `[workflow]` is unrelated: it times a run.

## Check a file

`hmp config check` loads the file, follows `base_config`, validates the merged result and
prints the path of the first error.

```text
$ hmp config check typo.toml
Config invalid: typo.toml: Unknown TOML key(s) in [flow]: flow_regme

$ hmp config check conflict.toml
Config invalid: 1 validation error(s) in conflict.toml:
  conflict.toml:3: flow.param.K.field.homogeneous: Value error, K.value mixes conflicting units: 'm/h' and 'm/s'.
```

The second file wrote `value = "0.36 m/h"` under a parent that had `unit = "m/s"`. The key
`unit` was inherited, so the two units disagreed. `hmp config targets <file>` lists the
names a calibration can move, with their value, unit and path.
