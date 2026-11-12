# Share a simulation with its data

A run, or a whole project, leaves your workspace as one archive that holds every file it read.
A colleague imports it into their own workspace and runs it again. The data lands in their
`data/`, next to their own files: identical bytes are not copied twice, and nothing of theirs
is overwritten.

## A run, in four commands

On your machine, publish the run. A copy takes its results and its inputs by default:

```bash
hmp publish nancon_step5_export --to sim.tar --container tar
```

On the other machine, import it into a project, rerun it, and compare the rerun with the copy:

```bash
hmp catalog import sim.tar -w ~/hydromodpy/projects/lab
hmp catalog rerun nancon_step5_export -w ~/hydromodpy/projects/lab
hmp diff nancon_step5_export nancon_step5_export.v2 -w ~/hydromodpy/projects/lab
```

`hmp catalog import` prints the last two commands with the names they take in that project.
On step 5 of example 04, the diff says `params: identical`, and the only metric that moves is
the solve time. The heads of the two runs are the same.

The results are the stores of the run (`fields.zarr`, `tables.parquet`) and its
`final_state/`, so the copy can be compared. `--without results` sends the configuration and
the data only, and `--without inputs` sends the run without the files it read. The copy also
holds the sealed mesh, `products.json` and a `.zenodo.json` that a Zenodo deposit reads.
A replay that is not classed `bit` is not published, because a published copy states that it
gives the sealed numbers: publish the source run, or a replay classed `bit`.

## What the inputs are

Every file the run read, as `inputs.json` names it, and nothing else:

| What the run read | Where it lands in the other workspace |
|---|---|
| A station series of your own (`hydrometry_custom_NANCON_..._D.csv`) | `data/hydrometry/`, with its row in `hydrometry_custom_LOC.csv` |
| The DEM of `[[data.dem.sources]]` (`source = "file"`), a GeoPackage of `[[data.hydrography.sources]]` | `data/dem/`, `data/hydrography/` |
| A file Hub'Eau, SIM2 or BD Topage delivered | the same folder, with its sidecar `<file>.json` and its station row |
| The `[site]` of the run | a row of `data/sites/catalog.csv` |

A declared folder is never copied whole: from `data/hydrometry/` the run takes the files of
the stations it read. The archive stores each file once, under its sha256, and lists them in
`INSTALL.toml`: the destination, the size, the sha256, the variable, the provider, the request,
the licence and the digest of the sidecar. The examples of `hmp example add` use the same index.

A file a provider delivered is installed with its sidecar, which `INSTALL.toml` completes, so the
file is a row of the data cache of the other workspace and a rerun reads it there instead of
downloading it again. A run of example 04 that read Hub'Eau and BD
Topage reruns with no network at all.

## The rules of an import

| What the workspace already holds | What the import does |
|---|---|
| Nothing at that path | Copies the file, with its sidecar |
| The same bytes at that path | Nothing: the file costs nothing |
| Other bytes at that path | Refuses, naming the path and both sha256 |
| The station with the same values | Nothing |
| The station with other values | Refuses, naming the registry and the station |
| A file of the data cache for the same station, from other bytes | Refuses, naming both files |
| A site of the same name with another outlet, or another name at the same outlet | Refuses, naming the site |

A refused import writes nothing: no file, no row, no run. Move your file aside, or import into
another workspace.

## Licences

Each input carries the licence its provider states: `etalab-2.0` for Hub'Eau, SIM2 and BD
Topage. A file of your own is `LicenseRef-undetermined` until you declare its licence, in the
`license` key of its sidecar:

```json
{"source": "file", "license": "CC-BY-4.0"}
```

`hmp publish --public` warns when the project declares no `[publication] license`, and when
the copy carries its inputs it warns and names each input that has no licence. The copy is
written anyway. It states `LicenseRef-undetermined` for what has no licence, and `INSTALL.toml`
and the RO-Crate state the licence of each input as it stands.

## The configuration travels without your paths

The frozen `config.toml` of a run names each input with a path relative to the project root,
typically under `inputs/`. Bare file names are no longer looked up in fallback workspace data
folders. The record of the run, `manifest.json` and `inputs.json`, names them relative to the
workspace (`data/dem/DEM_armorican_massif.tif`). No path of your machine leaves with the archive.

## A whole project

```bash
hmp publish nancon --package --to nancon.tar --with runs --with mesh --with fetched
hmp project import nancon.tar -w ~/hydromodpy
```

The archive holds the files you wrote at the root of the project (the TOML files, the scripts,
the README, `sites.csv`, `site_overrides/`) and every data file those TOML files reference, on
the same `INSTALL.toml`. On demand:

| Option | Adds |
|---|---|
| `--with runs` | the sealed runs, with their results and the files of your own they read |
| `--with sessions` | the calibration sessions |
| `--with mesh` | the mesh products the runs cite (`.hmp/products/`): gmsh cannot promise to draw the same mesh twice, this keeps the one the runs were computed on |
| `--with fetched` | the files the providers delivered to the runs, with their sidecars |

The project lands as `projects/<name>` of the workspace, with the same rules for its data. A
name the workspace already holds is refused; `--name` gives another one. The runs keep their
names.

## Without importing

`hmp replay <copy> -w <project>` replays a published copy from the bytes it carries ({doc}`../how-to/replay-a-run`).

## Check an archive

```bash
hmp publish --verify sim.tar
```

compares every file with the sha256 the archive lists. `hmp catalog import` and
`hmp project import` run the same check before they write anything.
