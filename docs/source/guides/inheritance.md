# Write a scenario by inheriting a file

```{hmp-task}
Task
: Write a variant of a TOML file that states only what changes: another recharge, another solver, another list of exports.

Time
: Minutes. The check is instant.

Needs
: A file that runs. The worked case is the staircase of example 04, from step 2 to step 6.

Gives
: A child file of a few lines, and the resolved file it makes, printed by `hmp config resolve`.
```

A TOML file can start from another one. The child writes only what changes. This guide shows
the rules on example 04 and the two ways to see the merged result. The grammar, with the
table of every rule, is in the {doc}`reference <../reference/parameters/grammar>`.

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

## What the merge does

The same function merges every layer: the files of the chain, then `--overlay` files, then
`--set` values. In short:

- a table that both files have is merged key by key, down to the leaves;
- a number, a string, a boolean or a list replaces the inherited value;
- a list of tables, `[[x]]`, replaces the inherited list too, whatever the lengths;
- four spellings change that for one key: `key__append`, `key__delete` and `key__merge`.

Inside one table, the merge works in three passes: the `key__delete` entries first, then
the file's own values, then the `key__append` entries. A key that neither file writes takes
the default of the model. An inherited value is not undone by that default: step 4 states
`flow_regime = "transient"` again because step 1 wrote `"steady"`, and the default would not
bring it back unless the file said so.

## Lists: replace, append, delete, merge

A list in the child replaces the list of the parent. This is the rule for lists of values,
`types = [...]`, and for lists of tables, `[[export]]`, alike. A child that rewrites the
three export blocks of step 1 gets exactly what it wrote:

```toml
[[export]]
variables = "watershed"
format = "shapefile"

[[export]]
variables = "head"

[[export]]
variables = "budget"
```

Merged onto step 1, the second block is `{variables = "head"}`. The `time = "last"` of
step 1's water table block does not come back. To start from the inherited list instead,
choose the form that says what you mean:

::::{tab-set}
:::{tab-item} Replace
Write the list again. The parent's list is gone, and the child's stands alone. This is what
step 4 does for `types`, and what step 3 does for its sources.

```toml
[data.hydrography]
sources = [{ source = "bdtopage" }]
```
:::
:::{tab-item} Add: __append
The child keeps the parent's items and adds its own. Steps 2, 3 and 4 do this with their
exports.

```toml
[[export__append]]
variables = "head"
format = "vtu"
```
:::
:::{tab-item} Drop: __delete
The child drops the parent's list, then writes its own. Step 5 does this with its exports.

```toml
export__delete = true

[[export]]
variables = "watershed"
format = "shapefile"
```
:::
:::{tab-item} Pair: __merge
The child changes some keys of each inherited table and keeps the others. One table per
inherited table, in order. Another length is refused.

```toml
[[export__merge]]
format = "shapefile"

[[export__merge]]
variables = ["head", "watertable_depth"]

[[export__merge]]
format = "csv"
```

Merged onto step 1, the second block keeps its `time = "last"` and takes the new variables.
:::
::::

`__merge` refuses what it cannot pair, with a message that says why: another length, no
inherited list, items that are not tables, or the plain key written too (see the table at the
end of this guide).

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

Merged onto step 2, this gives the same {toml}`data.types` as step 4. Two limits, both
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

For a list, `sources__delete = true` followed by a new list and the new list alone give the
same result, since a list replaces the parent's. Step 3 and step 5 write the delete anyway,
so the file says what it means whatever the rule of the loader becomes.

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

On your own file, two commands show the result without running anything:

::::{tab-set}
:::{tab-item} Resolve the chain
```bash
hmp config resolve step4_transient.toml
```

It prints the TOML that the chain makes, before validation: every table, with the lists as
the merge left them. It prints only what the files say, without the defaults of the model.
Redirect it to a file to keep a frozen copy, or to a pager to search a key.
:::
:::{tab-item} Check the result
```bash
hmp config check step4_transient.toml
```

It follows the chain, validates the merged result and prints `OK:` and the path. After a
run, `runs/<name>/config.toml` is the exact resolved configuration, frozen.
:::
::::

Example: `hmp config resolve step3_api_data.toml` prints `sources = [{ source = "bdtopage" }]`
under `[data.hydrography]`. No key of step 2 survives in it.

## Overlays and `--set`

`hmp run` has two more layers, applied after the chain, in this order: `--overlay FILE`
(repeatable, later files win), then `--set PATH=VALUE`. An overlay file may have its own
`base_config`, and it goes through the same merge function, so `__append`, `__delete` and
`__merge` work in it. `hmp config resolve` prints the chain only, not the overlays.

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

## How to check it worked

- `hmp config resolve child.toml` shows the list you meant: the blocks you wrote, or the
  inherited ones plus yours.
- `hmp config check child.toml` prints `OK:` and the path.
- Put the child next to its parent and run `hmp catalog diff` on the two runs: it names
  only what you changed ({doc}`find-and-compare-runs`).

## What can go wrong

| What you see | Cause | Fix |
|---|---|---|
| `Detected circular base_config chain: <a.toml> -> <b.toml> -> <a.toml>` | A file reaches itself through its bases. | Remove one link. |
| `base_config must be a TOML string path when provided` | The value is not a string. | Write a quoted path. |
| `File not found` or `[Errno 2] No such file or directory` on a `base_config` | The path is read from the folder of the file that holds it, not from where you run. | Fix the path. |
| `base_config` is ignored and its table fails | It came after a `[table]` header, so it is a key of that table. | Move it above the first table. |
| `merge directive '<key>__merge' has <n> table(s) and the inherited list has <m>; write one table per inherited table, or replace the list with '<key>'` | `__merge` pairs tables in order and the lengths differ. | Write one table per inherited table, or replace the list. |
| `merge directive '<key>__merge' has no inherited list to merge with` | The parent does not have the list. | Write the plain key. |
| `merge directive '<key>__merge' needs an inherited list of tables (found <type>)` | The inherited value is not a list of tables. | Write the plain key, or `__append` for a list of values. |
| `merge directive '<key>__merge' requires a list of tables` | The value is not a list of tables. | Write `[[<key>__merge]]` blocks. |
| `'<key>' and '<key>__merge' are both set; write only one of them` | The file writes the plain key and the directive. | Keep one. |
| `flow.param.K.field.heterogeneous.value: Extra inputs are not permitted` | The table changed shape and kept the key of the old shape. | Add `value__delete = true`, or drop the whole table. |
| `flow.param contains ids not declared in flow.param_list: Ss` | A child added a parameter table and left the inherited `param_list`. | Write `param_list__append = ["Ss"]`, or leave `param_list` out of every file. |
| A key you deleted is still there | A typo in `key__delete`. Deleting a key that does not exist is silent. | Check the spelling against `hmp config resolve`. |
| `merge directive '<key>__delete' requires the literal boolean true` | Only the literal `true` is accepted. | Write `key__delete = true`. |
| `merge directive '<key>__append' requires a list value, got <type>` | The value of `__append` is not a list. | Write a list. |

## See also

- The grammar of the file, with the table of every rule: {doc}`../reference/parameters/grammar`.
- Check the file while you type it: {doc}`set-up-your-editor`.
- The staircase, one page per step: {doc}`../get-started/staircase/index`.
- Where `[[export]]` is described: {doc}`../reference/parameters/export`, and the guide
  {doc}`export-results`.
