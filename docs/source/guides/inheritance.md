# Write a scenario by inheriting a file

A TOML file can start from another one. The child writes only what changes: another
recharge, another solver, another list of exports. This guide gives the exact merge rules,
read from the code, and shows each one on example 04, from step 2 to step 6.

## The line that does it

```{hmp-step} step2_local_data.toml
```

`base_config = "step1_minimal.toml"` is the first line of step 2. The `+` marks what the
file adds to what it inherits, and `~` what it changes.

- **Place it before the first table.** Written after a `[table]` header, it becomes a key
  of that table and is not read as inheritance.
- **The path is relative to the file that holds it**, not to the folder you run from. An
  absolute path works too, and `~` is expanded.
- **Chains are allowed.** The grandparent is merged first, then the parent, then the
  child. Step 5 is four files deep: step 5, step 4, step 2, step 1.
- **A cycle is an error.** The loader stops with `Detected circular base_config chain`.
- **The key does not survive.** Once the files are merged, `base_config` is gone.
- **The merged result is what is validated.** A child alone is not a complete file.
  `hmp config check step2_local_data.toml` follows the chain and validates the whole.

## The rules of the merge

The same function merges every layer: the files of the chain, then `--overlay` files, then
`--set` values. Inside one table, it works in three passes: first the `key__delete`
entries, then the file's own values, then the `key__append` entries.

| What the child writes | What the result holds |
|---|---|
| A table the parent also has | The two are merged key by key, down to the leaves. |
| A number, a string, a boolean | It replaces the parent's value. |
| A list of plain values, `types = [...]` | It **replaces** the parent's list. |
| A list of tables, `[[x]]`, of another length | It **replaces** the parent's list. |
| A list of tables, `[[x]]`, of the **same length** | The two are merged **element by element**. See the trap below. |
| `key__append = [...]` | The items are added after the parent's. |
| `key__delete = true` | The inherited key, or table, is removed. |
| A key neither file writes | The default of the model. |

A value that is inherited is not undone by the default. Step 4 states `flow_regime =
"transient"` again for that reason: step 1 wrote `"steady"`, and the default would not
bring it back unless the file said so.

## The trap: lists of tables of the same length

Two lists of tables of the same length look like one list that you rewrote. They are not.
The code merges the first element with the first, the second with the second, and so on.
Keys that the child does not repeat come back from the parent, without a message.

Step 3 changes the source of the network, from a local file to the BD Topage API. Step 2
declares one source, and step 3 declares one source. Here is the merged result of the real
loader when the line `sources__delete = true` is removed from step 3:

```toml
# Computed with the loader, not written by hand.
[[data.hydrography.sources]]
source = "bdtopage"
path = "nancon_stream_network.gpkg"   # leaked from step 2
```

The file is still valid: the schema accepts it, and nothing says that `path` came from
another file. The same happens to the gauge: `path = "hydrometry"` comes back beside the
Hub'Eau source. This is why step 3 writes `sources__delete = true` in `[data.hydrography]`
and in `[data.hydrometry]`. With it, the inherited list is dropped first, and the new one
stands alone.

```{hmp-step} step3_api_data.toml
```

The same trap in a list you may write often, `[[export]]`. Take step 1, which declares
three export blocks, and a child that rewrites three blocks:

```toml
[[export]]
variables = "watershed"
format = "shapefile"

[[export]]
variables = "head"

[[export]]
variables = "budget"
```

The second block comes out as `{variables = "head", time = "last"}`: the `time = "last"` of
step 1's water table block has leaked. Write the same child with one block more, or one
block less, and nothing leaks, because the lengths differ. A rule that depends on a
coincidence is a rule to avoid. Two safe ways:

::::{tab-set}
:::{tab-item} Start again: __delete
The child drops the parent's blocks, then writes its own. This is what step 5 does.

```toml
export__delete = true

[[export]]
variables = "watershed"
format = "shapefile"
```
:::
:::{tab-item} Add: __append
The child keeps the parent's blocks and adds its own. This is what steps 2, 3 and 4 do.

```toml
[[export__append]]
variables = "head"
format = "vtu"
```
:::
::::

## Add to a list: `__append`

In example 04 the exports grow along the staircase. Step 1 declares three blocks, and each
step adds its own with `[[export__append]]`: step 2 holds four, step 3 five, step 4 six.

```{hmp-toml}
:file: step2_local_data.toml
:tables: export__append
```

`__append` works on plain lists too. Step 4 writes the four data families again because a
list replaces the parent's. It could add the two new ones:

```{hmp-toml}
[data]
types__append = ["recharge", "runoff"]

[[data.recharge.sources]]
source = "custom"
path = "recharge"
station_ids = ["NANCON"]

[[data.runoff.sources]]
source = "custom"
path = "runoff"
station_ids = ["NANCON"]
```

Merged onto step 2, this gives the same `{toml}`data.types` as step 4. Two limits, both
raised as errors:

- the value of `key__append` must be a list;
- if the parent holds the key, it must be a list too. If the parent does not have the key,
  the appended list becomes the value.

## Delete: a key or a whole table

`key__delete = true` removes `key` from the merged result. Only the literal `true` is
accepted. In example 04:

| File | Line | What goes |
|---|---|---|
| step 3 | `sources__delete = true`, in `[data.hydrography]` and `[data.hydrometry]` | Step 2's local sources. |
| step 5 | `export__delete = true`, at the top of the file | All the export blocks of steps 1 to 4. |
| step 6 | `recharge__delete = true` and `runoff__delete = true`, in `[data]` | Two whole tables of `project.toml`. |
| step 6 | `export__delete = true`, at the top of the file | The exports of `project.toml`. |

```{hmp-toml}
:file: step6_soil_reservoir.toml
:tables: data
```

Three details that the code settles:

- A file can delete a key and write it again. The delete runs first, so the new value is
  not merged with the old one. That is how step 3 and step 5 work.
- Deleting a key that does not exist is silent. A typo in `sources__delete` removes
  nothing, and the parent's list stays.
- After a delete, a key that the file does not write comes back as the default of the model.

Step 5's `export__delete` changes nothing today, because step 4 holds 6 blocks and step 5
writes 11, and a list of another length replaces the parent's anyway. Step 6 writes 4
blocks over the 4 of `project.toml`, and the merge happens to give the same result. In both
cases the delete makes the file safe whatever the lengths become.

## Change the shape of an inherited table

Tables merge key by key, so a table that changes shape keeps the keys of its old shape. Step
1 gives K as one value for the aquifer. A child that wants K per zone must remove `value`:

```{hmp-toml}
[flow.param.K.field]
kind = "heterogeneous"
value__delete = true
field_spatial_id = "geology"
values = { zone_1 = 1e-5, zone_2 = 3e-4 }
```

Without `value__delete = true`, the validation says `flow.param.K.field.heterogeneous.value:
Extra inputs are not permitted`. The inherited `unit = "m/s"` stays, and it is still
right. The check above covers the schema only: `field_spatial_id` must name a support that
{toml}`domain.supports` declares, and {doc}`k-per-zone` shows how.

When the new shape shares nothing with the old one, drop the whole table and write it
again:

```{hmp-toml}
[flow.param]
K__delete = true

[flow.param.K.field]
kind = "heterogeneous"
unit = "m/s"
field_spatial_id = "geology"
values = { zone_1 = 1e-5, zone_2 = 3e-4 }
```

## Which file set this value?

Four files deep, it is not obvious. Followed through the chain, each value comes from one
file and one line:

```{hmp-resolved} flow.param.Ss.field.value
:config: step4_transient.toml
```

```{hmp-resolved} flow.param.K.field.value
:config: step4_transient.toml
```

To check it yourself:

- `hmp config check <file>` follows the chain and validates the merged result.
- After a run, `runs/<name>/config.toml` is the exact resolved configuration, frozen.

## Overlays and `--set`

`hmp run` has two more layers, applied after the chain, in this order: `--overlay FILE`
(repeatable, later files win), then `--set PATH=VALUE`. An overlay file may have its own
`base_config`, and it goes through the same merge function, so `__append` and `__delete`
work in it.

## When to inherit

Example 04 uses inheritance in three ways:

- **A staircase.** Each step adds one thing to its parent, and the diff is the lesson.
  Step 3 hangs off step 2 as a side branch, and step 4 also builds on step 2.
- **A frozen reference.** `project.toml` is the complete file. The calibration files,
  `run_daily.toml` and step 6 inherit it and write only their difference.
- **One file per question.** A family of scenarios shares a parent, and a change in the
  parent reaches all of them. That is also the risk: read the parent before you edit it.

Copy a file instead when the two have grown apart so far that the child would delete more
than it keeps.

## See also

- The grammar of the file: {doc}`../reference/parameters/grammar`.
- The staircase, one page per step: {doc}`../get-started/staircase/index`.
- Where `[[export]]` is described: {doc}`../reference/parameters/export`.
