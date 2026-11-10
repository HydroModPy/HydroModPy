# Replay a run

A replay plays a sealed run again and says whether it gives the same numbers. I use it to check
a run I kept, to read a run a colleague sent me, and to see what a new version changed. The run
it reads is never rewritten: the replay is a new version beside it.

## Play it

```bash
hmp replay runs/nancon_daily
```

The reference is a run directory inside a project, or a published copy. A copy outside a
project needs the project it goes to:

```bash
hmp replay ~/shared/nancon_copy -w ~/projects/nancon
```

The replay writes a new version of the same stem, `runs/nancon_daily.v2`, and seals it. It reads
the configuration the run sealed and the digests of `inputs.json`, so an input whose bytes moved
is refused with both digests. A URL is contacted only when the cache lacks the file. Its bytes
are not pinned, so values that move with them show in the class of the replay.

I add `--strict` when a difference must stop me:

```bash
hmp replay runs/nancon_daily --strict
```

With `--strict` a replay that differs ends failed, its fields and tables stay readable, and no
seal is written. Without it the replay is sealed whatever it found, and the class it wrote says
what happened.

## Read the lineage

The seal of the replay carries `lineage.kind = "replay"` and `parent_sim_id`, the `sim_id` of the
source. Its block `lineage.replay` holds what it compared and what it found.

| field | says |
|---|---|
| `basis` | `float64` for a seal of 2.1, `stored` for a run of 2.0, `none` when the source carries no values |
| `class` | `bit` when every value hashes the same, `deviation` otherwise, and none without a basis |
| `differs` | each key that differs, with `max_abs` and `rel_l2` of the whole field and the precision of the values it read |
| `added`, `removed` | the keys present on one side only |
| `producer` | each field of `provenance.json` that differs, with the sealed value and the value found |
| `changes` | the entries of the register of changes the source crossed |
| `strict` | whether I asked for the refusal |

On a run of 2.1 the comparison reads the value digests of the source seal, one per field and per
column of a quantity, taken in double precision. A field that is rounded for storage is hashed
before the rounding, so `bit` holds the calculated value and not the stored one. On a run of 2.0
the comparison reads the stored values of both sides, so `bit` holds to the rounding of 2^-17 on
a compact precision and to the last bit on an exact one, which is the case of most of the
reference runs.

The README of the replay says the class in its lineage section, and `lineage.replay` in
`runs/nancon_daily.v2/manifest.json` keeps the whole record. `hmp catalog show` gives the
summary of the run beside it.

## What a class does not refuse

A configuration that moved does not refuse a replay. The keys that differ from the sealed
`config.resolved.toml` go in `lineage.drift`, and the class measures what they changed. A default
this version added, absent from the sealed file and at its own default, is not a difference. A
solver binary that differs goes in `lineage.replay.producer`, with a line in the log, and the
replay runs. A replay classed `deviation` is sealed all the same, and `hmp publish` refuses it,
because the level of publication is read in the lineage.

Two things still refuse. An input whose digest differs is refused before anything runs, because
the run cannot read the bytes it sealed. A folder with no seal is refused, because there is
nothing to compare with.

## Replay a run of 2.0

A run sealed by 2.0 opens as it is and replays like any other. The comparison reads its stored
values, so its `basis` is `stored`. A run sealed by a pre-release has no stable reader and is
refused with its sentence; I play its `config.toml` again if I still have it.
